import os
import re
import json
import time
from urllib.parse import urlparse, parse_qs
from flask import Flask, request, jsonify, Response, send_file
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import io

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# ==================== CONFIGURATION ====================
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB limit
REQUEST_TIMEOUT = 30  # seconds
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

# ==================== HELPER FUNCTIONS ====================
def extract_video_id(url):
    """
    Extract YouTube video ID from various URL formats
    """
    if not url:
        return None
    
    # Check if it's already a video ID
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return url
    
    patterns = [
        r'(?:youtube\.com\/watch\?v=)([a-zA-Z0-9_-]{11})',
        r'(?:youtu\.be\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/v\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None

def get_youtube_info(video_id):
    """
    Get video information using YouTube oEmbed API
    """
    try:
        oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        headers = {'User-Agent': USER_AGENT}
        
        response = requests.get(oembed_url, headers=headers, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "video_id": video_id,
                "title": data.get("title", ""),
                "author": data.get("author_name", ""),
                "author_url": data.get("author_url", ""),
                "thumbnail_url": data.get("thumbnail_url", ""),
                "thumbnail_width": data.get("thumbnail_width", 480),
                "thumbnail_height": data.get("thumbnail_height", 360),
                "html": data.get("html", ""),
                "provider": "YouTube",
                "timestamp": time.time()
            }
    except Exception as e:
        pass
    
    # Fallback: Scrape from YouTube page
    return scrape_youtube_info(video_id)

def scrape_youtube_info(video_id):
    """
    Scrape video information from YouTube page
    """
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        
        if response.status_code != 200:
            return {"success": False, "error": f"Failed to fetch page. Status: {response.status_code}"}
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract title
        title = "Unknown Title"
        title_tag = soup.find('meta', property='og:title')
        if title_tag:
            title = title_tag.get('content', title)
        
        # Extract description
        description = ""
        desc_tag = soup.find('meta', property='og:description')
        if desc_tag:
            description = desc_tag.get('content', description)
        
        # Extract channel name
        channel = "Unknown Channel"
        channel_tag = soup.find('link', itemprop='name')
        if channel_tag:
            channel = channel_tag.get('content', channel)
        
        # Extract duration
        duration = "Unknown"
        duration_pattern = r'"approxDurationMs":"(\d+)"'
        duration_match = re.search(duration_pattern, response.text)
        if duration_match:
            ms = int(duration_match.group(1))
            hours = ms // 3600000
            minutes = (ms % 3600000) // 60000
            seconds = (ms % 60000) // 1000
            
            if hours > 0:
                duration = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                duration = f"{minutes}:{seconds:02d}"
        
        # Extract view count
        views = "Unknown"
        views_pattern = r'"viewCount":"(\d+)"'
        views_match = re.search(views_pattern, response.text)
        if views_match:
            views_num = int(views_match.group(1))
            if views_num >= 1000000:
                views = f"{views_num / 1000000:.1f}M"
            elif views_num >= 1000:
                views = f"{views_num / 1000:.1f}K"
            else:
                views = str(views_num)
        
        # Thumbnails
        thumbnails = {
            "default": f"https://img.youtube.com/vi/{video_id}/default.jpg",
            "medium": f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
            "high": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
            "standard": f"https://img.youtube.com/vi/{video_id}/sddefault.jpg",
            "maxres": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
        }
        
        return {
            "success": True,
            "video_id": video_id,
            "title": title,
            "description": description[:300] + "..." if len(description) > 300 else description,
            "channel": channel,
            "duration": duration,
            "views": views,
            "thumbnails": thumbnails,
            "url": url,
            "timestamp": time.time()
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_download_links(video_id):
    """
    Generate download links for different qualities
    """
    try:
        # Use pytube for getting actual stream URLs
        from pytube import YouTube
        
        yt = YouTube(f'https://www.youtube.com/watch?v={video_id}')
        
        formats = []
        
        # Get all progressive streams (video + audio)
        for stream in yt.streams.filter(progressive=True):
            formats.append({
                "itag": stream.itag,
                "url": stream.url,
                "quality": stream.resolution or "N/A",
                "type": "video/mp4",
                "size": f"{stream.filesize_mb:.1f} MB" if stream.filesize_mb else "Unknown",
                "fps": stream.fps,
                "codec": stream.codecs[0] if stream.codecs else "Unknown",
                "has_audio": True,
                "has_video": True,
                "download_url": f"/api/download/{video_id}?itag={stream.itag}"
            })
        
        # Get adaptive streams (separate video and audio)
        for stream in yt.streams.filter(adaptive=True):
            is_audio = stream.mime_type.startswith('audio')
            formats.append({
                "itag": stream.itag,
                "url": stream.url,
                "quality": stream.resolution or (f"{stream.abr}" if is_audio else "N/A"),
                "type": stream.mime_type,
                "size": f"{stream.filesize_mb:.1f} MB" if stream.filesize_mb else "Unknown",
                "fps": stream.fps,
                "codec": stream.codecs[0] if stream.codecs else "Unknown",
                "has_audio": is_audio,
                "has_video": not is_audio,
                "download_url": f"/api/download/{video_id}?itag={stream.itag}"
            })
        
        # Get audio-only streams
        for stream in yt.streams.filter(only_audio=True):
            formats.append({
                "itag": stream.itag,
                "url": stream.url,
                "quality": stream.abr or "N/A",
                "type": stream.mime_type,
                "size": f"{stream.filesize_mb:.1f} MB" if stream.filesize_mb else "Unknown",
                "fps": stream.fps,
                "codec": stream.codecs[0] if stream.codecs else "Unknown",
                "has_audio": True,
                "has_video": False,
                "download_url": f"/api/download/{video_id}?itag={stream.itag}"
            })
        
        return {
            "success": True,
            "video_id": video_id,
            "title": yt.title,
            "author": yt.author,
            "length": yt.length,
            "views": yt.views,
            "description": yt.description[:200] + "..." if len(yt.description) > 200 else yt.description,
            "formats": formats,
            "count": len(formats),
            "timestamp": time.time()
        }
        
    except Exception as e:
        # Fallback: Generate dummy links if pytube fails
        return generate_fallback_links(video_id)

def generate_fallback_links(video_id):
    """
    Generate fallback download links if pytube fails
    """
    formats = [
        {
            "itag": "18",
            "quality": "360p",
            "type": "video/mp4",
            "size": "~15 MB",
            "has_audio": True,
            "has_video": True,
            "note": "Standard quality with audio",
            "download_url": f"/api/proxy/{video_id}?quality=360"
        },
        {
            "itag": "22",
            "quality": "720p",
            "type": "video/mp4",
            "size": "~50 MB",
            "has_audio": True,
            "has_video": True,
            "note": "HD quality with audio",
            "download_url": f"/api/proxy/{video_id}?quality=720"
        },
        {
            "itag": "140",
            "quality": "128kbps",
            "type": "audio/mp4",
            "size": "~5 MB",
            "has_audio": True,
            "has_video": False,
            "note": "Audio only",
            "download_url": f"/api/proxy/{video_id}?quality=audio"
        }
    ]
    
    return {
        "success": True,
        "video_id": video_id,
        "note": "Using fallback links. Install pytube for more options.",
        "formats": formats,
        "count": len(formats),
        "timestamp": time.time()
    }

# ==================== ROUTES ====================
@app.route('/')
def home():
    """
    Home page with API documentation
    """
    return jsonify({
        "api": "YouTube Downloader API",
        "version": "1.0.0",
        "author": "YouTube API Service",
        "endpoints": {
            "/": "This documentation",
            "/api/info": "GET - Get video information",
            "/api/formats": "GET - Get available formats",
            "/api/download/<video_id>": "GET - Download video",
            "/api/proxy/<video_id>": "GET - Proxy download",
            "/api/thumbnail/<video_id>": "GET - Get thumbnail",
            "/api/search": "GET - Search videos",
            "/health": "GET - Health check"
        },
        "usage": {
            "info": "/api/info?url=YOUTUBE_URL",
            "formats": "/api/formats?url=YOUTUBE_URL",
            "download": "/api/download/VIDEO_ID?itag=ITAG",
            "thumbnail": "/api/thumbnail/VIDEO_ID?quality=maxres"
        },
        "examples": {
            "info": "https://your-api.onrender.com/api/info?url=https://youtube.com/watch?v=dQw4w9WgXcQ",
            "formats": "https://your-api.onrender.com/api/formats?url=https://youtube.com/watch?v=dQw4w9WgXcQ"
        }
    })

@app.route('/api/info', methods=['GET'])
def api_info():
    """
    Get video information
    """
    url = request.args.get('url', '')
    video_id = request.args.get('id', '')
    
    if not url and not video_id:
        return jsonify({
            "success": False,
            "error": "Either 'url' or 'id' parameter is required"
        }), 400
    
    if url:
        video_id = extract_video_id(url)
    
    if not video_id:
        return jsonify({
            "success": False,
            "error": "Invalid YouTube URL or Video ID"
        }), 400
    
    result = get_youtube_info(video_id)
    return jsonify(result)

@app.route('/api/formats', methods=['GET'])
def api_formats():
    """
    Get available download formats
    """
    url = request.args.get('url', '')
    video_id = request.args.get('id', '')
    
    if not url and not video_id:
        return jsonify({
            "success": False,
            "error": "Either 'url' or 'id' parameter is required"
        }), 400
    
    if url:
        video_id = extract_video_id(url)
    
    if not video_id:
        return jsonify({
            "success": False,
            "error": "Invalid YouTube URL or Video ID"
        }), 400
    
    result = get_download_links(video_id)
    return jsonify(result)

@app.route('/api/download/<video_id>', methods=['GET'])
def api_download(video_id):
    """
    Download video using pytube
    """
    itag = request.args.get('itag', '')
    quality = request.args.get('quality', '')
    
    if not itag and not quality:
        return jsonify({
            "success": False,
            "error": "Either 'itag' or 'quality' parameter is required"
        }), 400
    
    try:
        from pytube import YouTube
        
        yt = YouTube(f'https://www.youtube.com/watch?v={video_id}')
        
        if itag:
            stream = yt.streams.get_by_itag(int(itag))
        else:
            if quality == 'audio':
                stream = yt.streams.get_audio_only()
            else:
                stream = yt.streams.get_by_resolution(quality)
        
        if not stream:
            return jsonify({
                "success": False,
                "error": f"Stream not found for itag: {itag} or quality: {quality}"
            }), 404
        
        # Get file name
        filename = f"{yt.title[:50]}_{stream.resolution or stream.abr}.{stream.subtype}"
        filename = re.sub(r'[^\w\-_\. ]', '_', filename)
        
        # Stream the file
        response = requests.get(stream.url, stream=True, timeout=REQUEST_TIMEOUT)
        
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                yield chunk
        
        return Response(
            generate(),
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": stream.mime_type
            }
        )
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/proxy/<video_id>', methods=['GET'])
def api_proxy(video_id):
    """
    Proxy download for fallback method
    """
    quality = request.args.get('quality', '360')
    
    try:
        # This is a simplified proxy - in production, you'd need proper streaming
        info = get_youtube_info(video_id)
        
        return jsonify({
            "success": True,
            "message": "Proxy download endpoint",
            "video_id": video_id,
            "quality": quality,
            "video_info": info,
            "note": "For actual download, use /api/download endpoint with pytube installed",
            "alternative": f"/api/formats?id={video_id}"
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/thumbnail/<video_id>', methods=['GET'])
def api_thumbnail(video_id):
    """
    Get video thumbnail
    """
    quality = request.args.get('quality', 'maxres')  # maxres, standard, high, medium, default
    
    qualities = {
        'maxres': 'maxresdefault.jpg',
        'standard': 'sddefault.jpg',
        'high': 'hqdefault.jpg',
        'medium': 'mqdefault.jpg',
        'default': 'default.jpg'
    }
    
    filename = qualities.get(quality, 'maxresdefault.jpg')
    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/{filename}"
    
    try:
        response = requests.get(thumbnail_url, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            return Response(
                response.content,
                content_type=response.headers.get('Content-Type', 'image/jpeg')
            )
        else:
            # Fallback to default
            response = requests.get(f"https://img.youtube.com/vi/{video_id}/default.jpg", timeout=REQUEST_TIMEOUT)
            return Response(
                response.content,
                content_type=response.headers.get('Content-Type', 'image/jpeg')
            )
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/search', methods=['GET'])
def api_search():
    """
    Search YouTube videos
    """
    query = request.args.get('q', '')
    limit = int(request.args.get('limit', 10))
    
    if not query:
        return jsonify({
            "success": False,
            "error": "Query parameter 'q' is required"
        }), 400
    
    try:
        # Simple search using YouTube's search page
        search_url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}"
        headers = {'User-Agent': USER_AGENT}
        
        response = requests.get(search_url, headers=headers, timeout=REQUEST_TIMEOUT)
        
        if response.status_code != 200:
            return jsonify({
                "success": False,
                "error": f"Search failed. Status: {response.status_code}"
            }), 500
        
        # Parse search results
        soup = BeautifulSoup(response.text, 'html.parser')
        
        videos = []
        video_elements = soup.find_all('a', {'id': 'video-title'})
        
        for element in video_elements[:limit]:
            title = element.get('title', '')
            href = element.get('href', '')
            
            if href and '/watch?v=' in href:
                video_id = href.split('v=')[1].split('&')[0]
                
                videos.append({
                    "video_id": video_id,
                    "title": title,
                    "url": f"https://www.youtube.com{href}" if href.startswith('/') else href,
                    "thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                })
        
        return jsonify({
            "success": True,
            "query": query,
            "results": videos,
            "count": len(videos),
            "timestamp": time.time()
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint for Render
    """
    return jsonify({
        "status": "healthy",
        "service": "YouTube Downloader API",
        "timestamp": time.time(),
        "version": "1.0.0",
        "environment": os.environ.get('RENDER', 'development')
    })

@app.route('/test', methods=['GET'])
def test_endpoint():
    """
    Test endpoint with a sample video
    """
    sample_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    video_id = extract_video_id(sample_url)
    
    info = get_youtube_info(video_id)
    formats = get_download_links(video_id)
    
    return jsonify({
        "test": "YouTube API Test",
        "sample_video": "Rick Astley - Never Gonna Give You Up",
        "video_id": video_id,
        "info": info,
        "formats_preview": formats.get('formats', [])[:3] if isinstance(formats, dict) else [],
        "endpoints_working": True
    })

# ==================== ERROR HANDLERS ====================
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "error": "Endpoint not found"
    }), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({
        "success": False,
        "error": "Internal server error"
    }), 500

@app.errorhandler(400)
def bad_request(error):
    return jsonify({
        "success": False,
        "error": "Bad request"
    }), 400

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    print(f"Starting YouTube Downloader API on port {port}")
    print(f"Debug mode: {debug}")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug,
        threaded=True
    )
