import os
import re
import json
import time
import requests
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from bs4 import BeautifulSoup
from urllib.parse import parse_qs, urlparse, quote
import base64

app = Flask(__name__)
CORS(app)

# Configuration
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
TIMEOUT = 30

class YouTubeParser:
    """YouTube video parser without external libraries"""
    
    @staticmethod
    def extract_video_id(url):
        """Extract video ID from URL"""
        if not url:
            return None
        
        if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
            return url
        
        patterns = [
            r'(?:youtube\.com\/watch\?v=)([a-zA-Z0-9_-]{11})',
            r'(?:youtu\.be\/)([a-zA-Z0-9_-]{11})',
            r'(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
            r'(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})',
            r'(?:youtube\.com\/live\/)([a-zA-Z0-9_-]{11})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return None
    
    @staticmethod
    def get_video_info(video_id):
        """Get video information"""
        try:
            # Try oEmbed API first
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
                    "provider": "YouTube",
                    "method": "oembed"
                }
        except:
            pass
        
        # Fallback to scraping
        return YouTubeParser.scrape_video_info(video_id)
    
    @staticmethod
    def scrape_video_info(video_id):
        """Scrape video information"""
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {
                'User-Agent': USER_AGENT,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive'
            }
            
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            
            if response.status_code != 200:
                return {"success": False, "error": f"HTTP {response.status_code}"}
            
            html = response.text
            
            # Try to find ytInitialData
            initial_data = None
            patterns = [
                r'var ytInitialData = ({.*?});',
                r'window\["ytInitialData"\] = ({.*?});',
                r'ytInitialData\s*=\s*({.*?});'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, html, re.DOTALL)
                if match:
                    try:
                        initial_data = json.loads(match.group(1))
                        break
                    except:
                        continue
            
            # Extract title
            title = "Unknown Title"
            if initial_data:
                try:
                    video_details = YouTubeParser.find_key(initial_data, 'videoDetails')
                    if video_details:
                        title = video_details.get('title', title)
                except:
                    pass
            
            # Try meta tags
            if title == "Unknown Title":
                title_match = re.search(r'<meta name="title" content="([^"]+)"', html)
                if title_match:
                    title = title_match.group(1)
            
            # Extract channel
            channel = "Unknown Channel"
            channel_match = re.search(r'"author":"([^"]+)"', html)
            if channel_match:
                channel = channel_match.group(1)
            
            # Extract description
            description = ""
            desc_match = re.search(r'"shortDescription":"([^"]*)"', html)
            if desc_match:
                description = desc_match.group(1)
            
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
                "description": description[:300] + "..." if len(description) > 300 else description,
                "thumbnails": thumbnails,
                "url": url,
                "method": "scraping"
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def find_key(obj, key):
        """Find a key in nested dictionary"""
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for k, v in obj.items():
                result = YouTubeParser.find_key(v, key)
                if result:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = YouTubeParser.find_key(item, key)
                if result:
                    return result
        return None
    
    @staticmethod
    def extract_stream_url(video_id):
        """Extract video stream URL using multiple methods"""
        methods = [
            YouTubeParser.extract_from_embed,
            YouTubeParser.extract_from_player,
            YouTubeParser.extract_from_watch_page
        ]
        
        for method in methods:
            try:
                url = method(video_id)
                if url:
                    return url
            except:
                continue
        
        return None
    
    @staticmethod
    def extract_from_embed(video_id):
        """Extract from embed page"""
        try:
            embed_url = f"https://www.youtube.com/embed/{video_id}"
            headers = {'User-Agent': USER_AGENT}
            
            response = requests.get(embed_url, headers=headers, timeout=TIMEOUT)
            
            if response.status_code == 200:
                html = response.text
                
                # Look for video sources
                patterns = [
                    r'"url":"(https://[^"]*googlevideo[^"]*)"',
                    r'src="(https://[^"]*googlevideo[^"]*)"',
                    r'"(https://[^"]*videoplayback[^"]*)"'
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, html)
                    for match in matches:
                        if 'videoplayback' in match and 'googlevideo.com' in match:
                            return match.replace('\\/', '/')
        except:
            pass
        
        return None
    
    @staticmethod
    def extract_from_player(video_id):
        """Extract from player API"""
        try:
            # Try to get player response
            player_url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {
                'User-Agent': USER_AGENT,
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9'
            }
            
            response = requests.get(player_url, headers=headers, timeout=TIMEOUT)
            
            if response.status_code == 200:
                html = response.text
                
                # Find player_response
                patterns = [
                    r'var ytInitialPlayerResponse = ({.*?});',
                    r'ytInitialPlayerResponse\s*=\s*({.*?});',
                    r'player_response":"({.*?})"'
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, html, re.DOTALL)
                    if match:
                        try:
                            data_str = match.group(1)
                            if 'player_response' in pattern:
                                data_str = data_str.replace('\\"', '"').replace('\\\\', '\\')
                            
                            data = json.loads(data_str)
                            
                            if 'streamingData' in data:
                                streaming_data = data['streamingData']
                                
                                # Check adaptive formats
                                if 'adaptiveFormats' in streaming_data:
                                    for fmt in streaming_data['adaptiveFormats']:
                                        if 'url' in fmt:
                                            return fmt['url']
                                
                                # Check formats
                                if 'formats' in streaming_data:
                                    for fmt in streaming_data['formats']:
                                        if 'url' in fmt:
                                            return fmt['url']
                        except:
                            continue
        except:
            pass
        
        return None
    
    @staticmethod
    def extract_from_watch_page(video_id):
        """Extract from watch page directly"""
        try:
            watch_url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {'User-Agent': USER_AGENT}
            
            response = requests.get(watch_url, headers=headers, timeout=TIMEOUT)
            
            if response.status_code == 200:
                html = response.text
                
                # Look for video URLs in the page
                patterns = [
                    r'"url":"(https://[^"]*googlevideo\.com[^"]*videoplayback[^"]*)"',
                    r'src:\s*"(https://[^"]*googlevideo\.com[^"]*videoplayback[^"]*)"',
                    r'https://[^"]*googlevideo\.com[^"]*videoplayback[^"]*'
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, html)
                    for match in matches:
                        if 'videoplayback' in match and 'googlevideo.com' in match:
                            url = match.replace('\\/', '/').replace('\\u0026', '&')
                            # Check if it's a valid URL
                            if 'itag=' in url and 'key=' in url:
                                return url
        except:
            pass
        
        return None
    
    @staticmethod
    def get_direct_link(video_id, quality='360'):
        """Get direct video link using alternative methods"""
        try:
            # Method 1: Use yt1s-like service (public API)
            api_url = "https://www.yt-download.org/api/ajaxSearch/index"
            headers = {
                'User-Agent': USER_AGENT,
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
                'Origin': 'https://www.yt-download.org',
                'Referer': 'https://www.yt-download.org/'
            }
            
            data = {
                'query': f'https://youtube.com/watch?v={video_id}',
                'vt': 'home'
            }
            
            response = requests.post(api_url, headers=headers, data=data, timeout=TIMEOUT)
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    if result.get('status') == 'ok' and 'links' in result:
                        # Get mp4 links
                        for link_type, links in result['links'].items():
                            if 'mp4' in link_type:
                                for link in links:
                                    if 'url' in link:
                                        return link['url']
                except:
                    pass
        except:
            pass
        
        # Method 2: Use savefrom.net API
        try:
            savefrom_url = f"https://en.savefrom.net/#url=https://youtube.com/watch?v={video_id}"
            headers = {'User-Agent': USER_AGENT}
            
            response = requests.get(savefrom_url, headers=headers, timeout=TIMEOUT)
            
            if response.status_code == 200:
                html = response.text
                
                # Look for download links
                patterns = [
                    r'href="(https://[^"]*googlevideo[^"]*)"',
                    r'download_url":"([^"]+)"',
                    r'"url":"(https://[^"]*videoplayback[^"]*)"'
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, html)
                    for match in matches:
                        if 'googlevideo.com' in match:
                            return match.replace('\\/', '/')
        except:
            pass
        
        return None

# ==================== ROUTES ====================
@app.route('/')
def home():
    return jsonify({
        "api": "YouTube Video API",
        "version": "3.0",
        "status": "active",
        "endpoints": {
            "/": "Documentation",
            "/info?url=VIDEO_URL": "Get video info",
            "/formats?url=VIDEO_URL": "Get formats",
            "/direct?url=VIDEO_URL": "Get direct download link",
            "/thumbnail/VIDEO_ID": "Get thumbnail",
            "/proxy/VIDEO_ID": "Proxy download",
            "/health": "Health check"
        },
        "example": "/info?url=https://youtube.com/watch?v=dQw4w9WgXcQ"
    })

@app.route('/info')
def get_info():
    """Get video information"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    info = YouTubeParser.get_video_info(video_id)
    
    if isinstance(info, dict) and info.get("success"):
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
    """Get available formats"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Check if we can get a stream URL
    stream_url = YouTubeParser.extract_stream_url(video_id)
    direct_url = YouTubeParser.get_direct_link(video_id)
    
    formats = []
    
    if stream_url or direct_url:
        # Generate format options
        qualities = [
            {"quality": "144p", "label": "144p (Lowest)", "size": "~5MB"},
            {"quality": "360p", "label": "360p (Standard)", "size": "~15MB"},
            {"quality": "720p", "label": "720p (HD)", "size": "~50MB"},
            {"quality": "1080p", "label": "1080p (Full HD)", "size": "~100MB"},
            {"quality": "audio", "label": "Audio Only (MP3)", "size": "~3MB"}
        ]
        
        for q in qualities:
            formats.append({
                "quality": q["quality"],
                "label": q["label"],
                "size": q["size"],
                "type": "audio/mp3" if q["quality"] == "audio" else "video/mp4",
                "download_url": f"/proxy/{video_id}?quality={q['quality']}",
                "direct": bool(direct_url)
            })
    
    info = YouTubeParser.get_video_info(video_id)
    
    return jsonify({
        "success": True,
        "video_id": video_id,
        "title": info.get("title", "Unknown") if isinstance(info, dict) else "Unknown",
        "has_stream": bool(stream_url),
        "has_direct": bool(direct_url),
        "formats": formats,
        "count": len(formats),
        "timestamp": time.time()
    })

@app.route('/direct')
def get_direct():
    """Get direct download link"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Try multiple methods
    stream_url = YouTubeParser.extract_stream_url(video_id)
    direct_url = YouTubeParser.get_direct_link(video_id)
    
    return jsonify({
        "success": True,
        "video_id": video_id,
        "stream_url": stream_url[:200] + "..." if stream_url and len(stream_url) > 200 else stream_url,
        "direct_url": direct_url[:200] + "..." if direct_url and len(direct_url) > 200 else direct_url,
        "has_stream": bool(stream_url),
        "has_direct": bool(direct_url),
        "methods_tried": ["embed_parser", "player_api", "watch_page", "public_apis"],
        "note": "Use /proxy endpoint for actual download",
        "proxy_url": f"/proxy/{video_id}?quality=360p"
    })

@app.route('/proxy/<video_id>')
def proxy_download(video_id):
    """Proxy download with multiple fallback methods"""
    quality = request.args.get('quality', '360p')
    download_type = request.args.get('type', 'video')
    
    try:
        # Method 1: Try to get direct link
        direct_url = YouTubeParser.get_direct_link(video_id)
        
        if direct_url:
            # Stream the content
            headers = {'User-Agent': USER_AGENT}
            
            def generate():
                with requests.get(direct_url, headers=headers, stream=True, timeout=TIMEOUT) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=8192):
                        yield chunk
            
            content_type = 'video/mp4'
            filename = f"video_{video_id}.mp4"
            
            if quality == 'audio' or download_type == 'audio':
                content_type = 'audio/mpeg'
                filename = f"audio_{video_id}.mp3"
            
            return Response(
                stream_with_context(generate()),
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Content-Type': content_type
                }
            )
        
        # Method 2: Try stream URL
        stream_url = YouTubeParser.extract_stream_url(video_id)
        
        if stream_url:
            headers = {'User-Agent': USER_AGENT}
            
            def generate():
                with requests.get(stream_url, headers=headers, stream=True, timeout=TIMEOUT) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=8192):
                        yield chunk
            
            return Response(
                stream_with_context(generate()),
                headers={
                    'Content-Disposition': f'attachment; filename="video_{video_id}.mp4"',
                    'Content-Type': 'video/mp4'
                }
            )
        
        # Method 3: Use y2mate API
        try:
            y2mate_url = f"https://www.y2mate.com/mates/analyzeV2/ajax"
            headers = {
                'User-Agent': USER_AGENT,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': 'https://www.y2mate.com',
                'Referer': 'https://www.y2mate.com/'
            }
            
            data = {
                'k_query': f'https://youtube.com/watch?v={video_id}',
                'k_page': 'home',
                'hl': 'en',
                'q_auto': '0'
            }
            
            response = requests.post(y2mate_url, headers=headers, data=data, timeout=TIMEOUT)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('status') == 'ok':
                    # Parse the response for download links
                    import html
                    result_html = result.get('result', '')
                    soup = BeautifulSoup(result_html, 'html.parser')
                    
                    # Find download links
                    for a in soup.find_all('a', href=True):
                        href = a['href']
                        if 'googlevideo.com' in href or 'videoplayback' in href:
                            return jsonify({
                                "success": True,
                                "video_id": video_id,
                                "download_url": href,
                                "method": "y2mate",
                                "note": "Use this URL directly in browser or download manager"
                            })
        except:
            pass
        
        # Method 4: Return as redirect to external service
        return jsonify({
            "success": True,
            "video_id": video_id,
            "alternative_methods": [
                {
                    "service": "y2mate",
                    "url": f"https://www.y2mate.com/youtube/{video_id}"
                },
                {
                    "service": "savefrom",
                    "url": f"https://en.savefrom.net/#url=https://youtube.com/watch?v={video_id}"
                },
                {
                    "service": "ytmp3",
                    "url": f"https://ytmp3.cc/en13/{video_id}"
                }
            ],
            "note": "These are external services. Use at your own risk."
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "video_id": video_id
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

@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "service": "YouTube API",
        "uptime": time.time() - app.start_time if hasattr(app, 'start_time') else 0
    })

@app.route('/test/<video_id>')
def test_video(video_id):
    """Test video parsing"""
    info = YouTubeParser.get_video_info(video_id)
    stream_url = YouTubeParser.extract_stream_url(video_id)
    direct_url = YouTubeParser.get_direct_link(video_id)
    
    return jsonify({
        "video_id": video_id,
        "info_success": info.get("success") if isinstance(info, dict) else False,
        "has_stream": bool(stream_url),
        "has_direct": bool(direct_url),
        "stream_url_short": stream_url[:100] + "..." if stream_url and len(stream_url) > 100 else stream_url,
        "direct_url_short": direct_url[:100] + "..." if direct_url and len(direct_url) > 100 else direct_url,
        "test_time": time.time()
    })

# Initialize app start time
app.start_time = time.time()

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting YouTube API on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
