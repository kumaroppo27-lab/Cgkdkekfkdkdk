import os
import re
import json
import time
import requests
from flask import Flask, request, jsonify, Response, send_file, stream_with_context
from flask_cors import CORS
from bs4 import BeautifulSoup
import io
from urllib.parse import urlparse, parse_qs, quote

app = Flask(__name__)
CORS(app)

# Configuration
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
TIMEOUT = 30

# ==================== VIDEO DOWNLOADER CLASS ====================
class YouTubeDownloader:
    """YouTube video downloader without external APIs"""
    
    @staticmethod
    def extract_video_id(url):
        """Extract video ID from URL"""
        patterns = [
            r'(?:youtube\.com\/watch\?v=)([a-zA-Z0-9_-]{11})',
            r'(?:youtu\.be\/)([a-zA-Z0-9_-]{11})',
            r'(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
            r'(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
            return url
        
        return None
    
    @staticmethod
    def get_video_info(video_id):
        """Get video information using oEmbed"""
        try:
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            headers = {'User-Agent': USER_AGENT}
            
            response = requests.get(oembed_url, headers=headers, timeout=TIMEOUT)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "video_id": video_id,
                    "title": data.get("title", ""),
                    "author": data.get("author_name", ""),
                    "author_url": data.get("author_url", ""),
                    "thumbnail_url": data.get("thumbnail_url", ""),
                    "html": data.get("html", ""),
                    "provider": "YouTube"
                }
        except:
            pass
        
        return YouTubeDownloader.scrape_video_info(video_id)
    
    @staticmethod
    def scrape_video_info(video_id):
        """Scrape video information from YouTube page"""
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {'User-Agent': USER_AGENT}
            
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            
            if response.status_code != 200:
                return {"success": False, "error": "Failed to fetch video"}
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract title
            title = "Unknown Title"
            title_tag = soup.find('meta', property='og:title')
            if title_tag:
                title = title_tag.get('content', title)
            
            # Extract channel
            channel = "Unknown Channel"
            channel_tag = soup.find('link', itemprop='name')
            if channel_tag:
                channel = channel_tag.get('content', channel)
            
            # Extract description
            description = ""
            desc_tag = soup.find('meta', property='og:description')
            if desc_tag:
                description = desc_tag.get('content', description)
            
            # Thumbnails
            thumbnails = {
                "default": f"https://i.ytimg.com/vi/{video_id}/default.jpg",
                "medium": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
                "high": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "standard": f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
                "maxres": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
            }
            
            return {
                "success": True,
                "video_id": video_id,
                "title": title,
                "channel": channel,
                "description": description[:200] + "..." if len(description) > 200 else description,
                "thumbnails": thumbnails,
                "url": url
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def get_stream_url(video_id, quality='360p'):
        """Get direct stream URL from YouTube"""
        try:
            # YouTube video page URL
            url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {
                'User-Agent': USER_AGENT,
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive'
            }
            
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            
            if response.status_code != 200:
                return None
            
            # Extract player response
            html = response.text
            
            # Find ytInitialPlayerResponse
            patterns = [
                r'var ytInitialPlayerResponse = ({.*?});',
                r'ytInitialPlayerResponse\s*=\s*({.*?});',
                r'window\["ytInitialPlayerResponse"\]\s*=\s*({.*?});'
            ]
            
            player_response = None
            for pattern in patterns:
                match = re.search(pattern, html, re.DOTALL)
                if match:
                    try:
                        player_response = json.loads(match.group(1))
                        break
                    except:
                        continue
            
            if not player_response:
                # Try another method
                match = re.search(r'player_response":"({.*?})"', html)
                if match:
                    try:
                        player_response = json.loads(match.group(1).replace('\\"', '"'))
                    except:
                        pass
            
            if player_response and 'streamingData' in player_response:
                streaming_data = player_response['streamingData']
                
                # Get adaptive formats (highest quality)
                if 'adaptiveFormats' in streaming_data:
                    formats = streaming_data['adaptiveFormats']
                    
                    # Filter by quality
                    for fmt in formats:
                        if 'qualityLabel' in fmt and fmt['qualityLabel'] == quality:
                            if 'url' in fmt:
                                return fmt['url']
                
                # Get progressive formats
                if 'formats' in streaming_data:
                    formats = streaming_data['formats']
                    
                    for fmt in formats:
                        if 'qualityLabel' in fmt and fmt['qualityLabel'] == quality:
                            if 'url' in fmt:
                                return fmt['url']
                
                # Return first available format
                if 'adaptiveFormats' in streaming_data and streaming_data['adaptiveFormats']:
                    first_fmt = streaming_data['adaptiveFormats'][0]
                    if 'url' in first_fmt:
                        return first_fmt['url']
                
                if 'formats' in streaming_data and streaming_data['formats']:
                    first_fmt = streaming_data['formats'][0]
                    if 'url' in first_fmt:
                        return first_fmt['url']
            
            return None
            
        except Exception as e:
            print(f"Error getting stream URL: {e}")
            return None
    
    @staticmethod
    def get_download_formats(video_id):
        """Get available download formats"""
        try:
            stream_url = YouTubeDownloader.get_stream_url(video_id)
            if not stream_url:
                return []
            
            # Get video info
            info = YouTubeDownloader.get_video_info(video_id)
            
            # Generate format options
            formats = [
                {
                    "itag": "18",
                    "quality": "360p",
                    "type": "video/mp4",
                    "size": "~15-50MB",
                    "has_audio": True,
                    "download_url": f"/download/{video_id}?quality=360p"
                },
                {
                    "itag": "22",
                    "quality": "720p",
                    "type": "video/mp4",
                    "size": "~50-150MB",
                    "has_audio": True,
                    "download_url": f"/download/{video_id}?quality=720p"
                },
                {
                    "itag": "137",
                    "quality": "1080p",
                    "type": "video/mp4",
                    "size": "~100-300MB",
                    "has_audio": False,
                    "download_url": f"/download/{video_id}?quality=1080p"
                },
                {
                    "itag": "140",
                    "quality": "128kbps",
                    "type": "audio/mp4",
                    "size": "~3-10MB",
                    "has_audio": True,
                    "download_url": f"/download/{video_id}?quality=audio"
                }
            ]
            
            return {
                "success": True,
                "video_id": video_id,
                "title": info.get("title", "") if isinstance(info, dict) else "Unknown",
                "author": info.get("author", "") if isinstance(info, dict) else "Unknown",
                "formats": formats,
                "count": len(formats)
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}

# ==================== ROUTES ====================
@app.route('/')
def home():
    return jsonify({
        "api": "YouTube Video Downloader API",
        "version": "2.0",
        "author": "YouTube API",
        "endpoints": {
            "/": "API Documentation",
            "/info": "Get video information",
            "/formats": "Get available formats",
            "/download/<video_id>": "Download video",
            "/stream/<video_id>": "Stream video",
            "/thumbnail/<video_id>": "Get thumbnail",
            "/search": "Search videos",
            "/health": "Health check"
        },
        "usage": {
            "info": "/info?url=YOUTUBE_URL",
            "formats": "/formats?url=YOUTUBE_URL",
            "download": "/download/VIDEO_ID?quality=360p"
        }
    })

@app.route('/info')
def get_info():
    """Get video information"""
    url = request.args.get('url', '')
    video_id = request.args.get('id', '')
    
    if not url and not video_id:
        return jsonify({"error": "URL or ID required"}), 400
    
    if url:
        video_id = YouTubeDownloader.extract_video_id(url)
    
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    info = YouTubeDownloader.get_video_info(video_id)
    
    if isinstance(info, dict) and info.get("success", False):
        info["timestamp"] = time.time()
        return jsonify(info)
    else:
        return jsonify({
            "success": False,
            "error": "Failed to get video info",
            "video_id": video_id
        }), 500

@app.route('/formats')
def get_formats():
    """Get available download formats"""
    url = request.args.get('url', '')
    video_id = request.args.get('id', '')
    
    if not url and not video_id:
        return jsonify({"error": "URL or ID required"}), 400
    
    if url:
        video_id = YouTubeDownloader.extract_video_id(url)
    
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    formats = YouTubeDownloader.get_download_formats(video_id)
    
    if isinstance(formats, dict) and formats.get("success", False):
        formats["timestamp"] = time.time()
        return jsonify(formats)
    else:
        return jsonify({
            "success": False,
            "error": "Failed to get formats",
            "video_id": video_id
        }), 500

@app.route('/download/<video_id>')
def download_video(video_id):
    """Download video directly"""
    quality = request.args.get('quality', '360p')
    filename = request.args.get('filename', '')
    
    # Get stream URL
    stream_url = YouTubeDownloader.get_stream_url(video_id, quality)
    
    if not stream_url:
        return jsonify({
            "success": False,
            "error": "Could not get video stream URL"
        }), 500
    
    try:
        # Get video info for filename
        info = YouTubeDownloader.get_video_info(video_id)
        title = info.get('title', 'video') if isinstance(info, dict) and info.get('success') else 'video'
        
        # Clean filename
        if not filename:
            filename = re.sub(r'[^\w\-_\. ]', '_', title[:50])
            if quality == 'audio':
                filename += '.mp3'
            else:
                filename += f'_{quality}.mp4'
        
        # Stream the video
        headers = {'User-Agent': USER_AGENT}
        
        def generate():
            with requests.get(stream_url, headers=headers, stream=True, timeout=TIMEOUT) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=8192):
                    yield chunk
        
        content_type = 'audio/mpeg' if quality == 'audio' else 'video/mp4'
        
        return Response(
            stream_with_context(generate()),
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': content_type
            }
        )
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/stream/<video_id>')
def stream_video(video_id):
    """Stream video without download"""
    quality = request.args.get('quality', '360p')
    
    stream_url = YouTubeDownloader.get_stream_url(video_id, quality)
    
    if not stream_url:
        return jsonify({
            "success": False,
            "error": "Could not get stream URL"
        }), 500
    
    try:
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(stream_url, headers=headers, stream=True, timeout=TIMEOUT)
        
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                yield chunk
        
        content_type = 'video/mp4'
        if quality == 'audio':
            content_type = 'audio/mpeg'
        
        return Response(
            stream_with_context(generate()),
            content_type=content_type
        )
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/thumbnail/<video_id>')
def get_thumbnail(video_id):
    """Get video thumbnail"""
    quality = request.args.get('quality', 'maxres')
    
    qualities = {
        'maxres': 'maxresdefault.jpg',
        'standard': 'sddefault.jpg',
        'high': 'hqdefault.jpg',
        'medium': 'mqdefault.jpg',
        'default': 'default.jpg'
    }
    
    filename = qualities.get(quality, 'maxresdefault.jpg')
    thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/{filename}"
    
    try:
        response = requests.get(thumbnail_url, timeout=TIMEOUT)
        
        if response.status_code == 200:
            return Response(
                response.content,
                content_type='image/jpeg'
            )
        else:
            # Fallback
            response = requests.get(f"https://i.ytimg.com/vi/{video_id}/default.jpg", timeout=TIMEOUT)
            return Response(response.content, content_type='image/jpeg')
            
    except:
        return jsonify({"error": "Failed to get thumbnail"}), 500

@app.route('/search')
def search_videos():
    """Search YouTube videos"""
    query = request.args.get('q', '')
    limit = int(request.args.get('limit', 10))
    
    if not query:
        return jsonify({"error": "Query parameter 'q' is required"}), 400
    
    try:
        search_url = f"https://www.youtube.com/results?search_query={quote(query)}"
        headers = {'User-Agent': USER_AGENT}
        
        response = requests.get(search_url, headers=headers, timeout=TIMEOUT)
        
        if response.status_code != 200:
            return jsonify({"error": "Search failed"}), 500
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        videos = []
        
        # Find video links
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/watch?v=' in href:
                video_id = href.split('v=')[1].split('&')[0]
                
                # Check if we already have this video
                if not any(v['video_id'] == video_id for v in videos):
                    title = a.get('title', '')
                    if not title:
                        title = a.text.strip()
                    
                    if title and len(title) > 3 and video_id:
                        videos.append({
                            "video_id": video_id,
                            "title": title[:100],
                            "url": f"https://youtube.com{href}" if href.startswith('/') else href,
                            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                        })
                        
                        if len(videos) >= limit:
                            break
        
        return jsonify({
            "success": True,
            "query": query,
            "results": videos,
            "count": len(videos)
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "service": "YouTube Downloader API"
    })

@app.route('/test/<video_id>')
def test_video(video_id):
    """Test endpoint for a video"""
    info = YouTubeDownloader.get_video_info(video_id)
    formats = YouTubeDownloader.get_download_formats(video_id)
    stream_url = YouTubeDownloader.get_stream_url(video_id)
    
    return jsonify({
        "video_id": video_id,
        "info": info,
        "formats": formats,
        "has_stream_url": bool(stream_url),
        "test_passed": isinstance(info, dict) and info.get("success", False)
    })

# Error handlers
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Bad request"}), 400

# Run the app
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
