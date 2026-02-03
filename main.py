import os
import re
import json
import time
import requests
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from urllib.parse import parse_qs, unquote, quote
import base64

app = Flask(__name__)
CORS(app)

# Configuration
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
TIMEOUT = 30

class YouTubeDirectParser:
    """Direct YouTube video parser without any external APIs"""
    
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
    def get_player_response(video_id):
        """Get YouTube player response containing streaming data"""
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {
                'User-Agent': USER_AGENT,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive'
            }
            
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            
            if response.status_code != 200:
                return None
            
            html = response.text
            
            # Find player response in the HTML
            patterns = [
                r'var ytInitialPlayerResponse\s*=\s*({.*?});',
                r'ytInitialPlayerResponse\s*=\s*({.*?});',
                r'window\["ytInitialPlayerResponse"\]\s*=\s*({.*?});',
                r'player_response":"({.*?})"',
                r'"playerResponse":"({.*?})"'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, html, re.DOTALL)
                if match:
                    try:
                        json_str = match.group(1)
                        
                        # Clean the JSON string
                        json_str = json_str.replace('\\"', '"')
                        json_str = json_str.replace('\\\\', '\\')
                        json_str = json_str.replace('\\n', '')
                        json_str = json_str.replace('\\r', '')
                        
                        # Parse JSON
                        data = json.loads(json_str)
                        return data
                    except json.JSONDecodeError:
                        # Try decoding base64 if present
                        if 'player_response' in pattern:
                            try:
                                # Sometimes it's base64 encoded
                                import base64
                                decoded = base64.b64decode(json_str).decode('utf-8')
                                data = json.loads(decoded)
                                return data
                            except:
                                continue
                        continue
            
            return None
            
        except Exception as e:
            print(f"Error getting player response: {e}")
            return None
    
    @staticmethod
    def extract_stream_urls(player_response):
        """Extract streaming URLs from player response"""
        if not player_response:
            return []
        
        try:
            streaming_data = player_response.get('streamingData', {})
            formats = []
            
            # Get adaptive formats (separate video and audio)
            adaptive_formats = streaming_data.get('adaptiveFormats', [])
            for fmt in adaptive_formats:
                if 'url' in fmt:
                    # Video format
                    if 'video' in fmt.get('type', '').lower():
                        quality = fmt.get('qualityLabel', '')
                        if not quality and 'height' in fmt:
                            quality = f"{fmt['height']}p"
                        
                        formats.append({
                            'itag': fmt.get('itag', ''),
                            'quality': quality,
                            'type': fmt.get('type', ''),
                            'url': fmt['url'],
                            'has_video': True,
                            'has_audio': False,
                            'size': fmt.get('contentLength', ''),
                            'fps': fmt.get('fps', '')
                        })
                    
                    # Audio format
                    elif 'audio' in fmt.get('type', '').lower():
                        bitrate = fmt.get('bitrate', 0)
                        if bitrate:
                            quality = f"{bitrate // 1000}kbps"
                        else:
                            quality = "audio"
                        
                        formats.append({
                            'itag': fmt.get('itag', ''),
                            'quality': quality,
                            'type': fmt.get('type', ''),
                            'url': fmt['url'],
                            'has_video': False,
                            'has_audio': True,
                            'size': fmt.get('contentLength', '')
                        })
            
            # Get progressive formats (video + audio together)
            progressive_formats = streaming_data.get('formats', [])
            for fmt in progressive_formats:
                if 'url' in fmt:
                    quality = fmt.get('qualityLabel', '')
                    if not quality and 'height' in fmt:
                        quality = f"{fmt['height']}p"
                    
                    formats.append({
                        'itag': fmt.get('itag', ''),
                        'quality': quality,
                        'type': fmt.get('type', ''),
                        'url': fmt['url'],
                        'has_video': True,
                        'has_audio': True,
                        'size': fmt.get('contentLength', ''),
                        'fps': fmt.get('fps', '')
                    })
            
            return formats
            
        except Exception as e:
            print(f"Error extracting stream URLs: {e}")
            return []
    
    @staticmethod
    def parse_signature_cipher(cipher):
        """Parse signatureCipher to get URL"""
        if not cipher:
            return None
        
        try:
            # Parse the cipher parameters
            params = {}
            for param in cipher.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    params[key] = unquote(value)
            
            # Get the base URL
            url = params.get('url', '')
            if not url:
                return None
            
            # Add signature parameters if present
            sp = params.get('sp', 'signature')
            sig = params.get('s', '')
            
            if sig:
                # We would need to decode the signature here
                # This is a simplified version
                url = f"{url}&{sp}={sig}"
            
            return url
            
        except:
            return None
    
    @staticmethod
    def get_direct_links(video_id):
        """Get direct download links from YouTube"""
        player_response = YouTubeDirectParser.get_player_response(video_id)
        
        if not player_response:
            return {"error": "Could not get player response"}
        
        # Get video details
        video_details = player_response.get('videoDetails', {})
        title = video_details.get('title', '')
        author = video_details.get('author', '')
        length = video_details.get('lengthSeconds', 0)
        
        # Extract streaming URLs
        formats = YouTubeDirectParser.extract_stream_urls(player_response)
        
        # Process URLs to ensure they're direct
        processed_formats = []
        for fmt in formats:
            url = fmt.get('url', '')
            
            # Handle signatureCipher if present
            if not url and 'signatureCipher' in fmt:
                url = YouTubeDirectParser.parse_signature_cipher(fmt['signatureCipher'])
            
            if url:
                # Clean and validate URL
                if 'googlevideo.com' in url and 'videoplayback' in url:
                    processed_formats.append({
                        'itag': fmt.get('itag', ''),
                        'quality': fmt.get('quality', 'Unknown'),
                        'type': fmt.get('type', ''),
                        'url': url,
                        'has_video': fmt.get('has_video', False),
                        'has_audio': fmt.get('has_audio', False),
                        'size': YouTubeDirectParser.format_size(fmt.get('size', 0)),
                        'download_url': f"/direct-download/{video_id}?itag={fmt.get('itag', '')}"
                    })
        
        # Sort by quality
        quality_order = ['144p', '240p', '360p', '480p', '720p', '1080p', '1440p', '2160p']
        processed_formats.sort(key=lambda x: (
            quality_order.index(x['quality']) if x['quality'] in quality_order else 999,
            x['quality']
        ))
        
        return {
            'success': True,
            'video_id': video_id,
            'title': title,
            'author': author,
            'duration': YouTubeDirectParser.format_duration(length),
            'formats': processed_formats,
            'count': len(processed_formats)
        }
    
    @staticmethod
    def format_size(bytes_str):
        """Format file size"""
        try:
            bytes_int = int(bytes_str)
            if bytes_int == 0:
                return "Unknown"
            
            for unit in ['B', 'KB', 'MB', 'GB']:
                if bytes_int < 1024.0:
                    return f"{bytes_int:.1f} {unit}"
                bytes_int /= 1024.0
            return f"{bytes_int:.1f} TB"
        except:
            return "Unknown"
    
    @staticmethod
    def format_duration(seconds):
        """Format duration in seconds to HH:MM:SS"""
        try:
            seconds = int(seconds)
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            secs = seconds % 60
            
            if hours > 0:
                return f"{hours}:{minutes:02d}:{secs:02d}"
            else:
                return f"{minutes}:{secs:02d}"
        except:
            return "0:00"

# ==================== ROUTES ====================

@app.route('/')
def home():
    return jsonify({
        "api": "YouTube Direct Parser API",
        "version": "1.0",
        "description": "Direct YouTube video parser without external APIs",
        "endpoints": {
            "/parse?url=YOUTUBE_URL": "Parse video and get direct links",
            "/direct-download/VIDEO_ID": "Direct download endpoint",
            "/stream/VIDEO_ID": "Stream video",
            "/info?url=YOUTUBE_URL": "Get video info",
            "/health": "Health check"
        },
        "note": "This API directly parses YouTube without any external services"
    })

@app.route('/parse')
def parse_video():
    """Parse YouTube video and get direct download links"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeDirectParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    result = YouTubeDirectParser.get_direct_links(video_id)
    
    if result.get('success'):
        result['timestamp'] = time.time()
        return jsonify(result)
    else:
        return jsonify({
            "success": False,
            "error": result.get('error', 'Unknown error'),
            "video_id": video_id
        }), 500

@app.route('/direct-download/<video_id>')
def direct_download(video_id):
    """Direct download endpoint"""
    itag = request.args.get('itag', '')
    
    if not itag:
        return jsonify({"error": "itag parameter is required"}), 400
    
    # Get player response
    player_response = YouTubeDirectParser.get_player_response(video_id)
    if not player_response:
        return jsonify({"error": "Could not get video data"}), 500
    
    # Find the format with the given itag
    formats = YouTubeDirectParser.extract_stream_urls(player_response)
    
    target_format = None
    for fmt in formats:
        if str(fmt.get('itag', '')) == str(itag):
            target_format = fmt
            break
    
    if not target_format:
        return jsonify({"error": "Format not found"}), 404
    
    # Get the URL
    url = target_format.get('url', '')
    if not url and 'signatureCipher' in target_format:
        url = YouTubeDirectParser.parse_signature_cipher(target_format['signatureCipher'])
    
    if not url:
        return jsonify({"error": "Could not get download URL"}), 500
    
    try:
        # Stream the video
        headers = {'User-Agent': USER_AGENT}
        
        def generate():
            with requests.get(url, headers=headers, stream=True, timeout=TIMEOUT) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=8192):
                    yield chunk
        
        # Get video info for filename
        video_details = player_response.get('videoDetails', {})
        title = video_details.get('title', 'video')
        
        # Clean filename
        filename = re.sub(r'[^\w\-_\. ]', '_', title[:50])
        
        # Determine file extension
        content_type = target_format.get('type', 'video/mp4')
        extension = '.mp4'
        if 'audio' in content_type.lower():
            extension = '.mp3'
            content_type = 'audio/mpeg'
        
        filename += f'_{itag}{extension}'
        
        return Response(
            stream_with_context(generate()),
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': content_type
            }
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stream/<video_id>')
def stream_video(video_id):
    """Stream video directly"""
    itag = request.args.get('itag', '18')  # Default to 360p
    
    # Get player response
    player_response = YouTubeDirectParser.get_player_response(video_id)
    if not player_response:
        return jsonify({"error": "Could not get video data"}), 500
    
    # Find the format
    formats = YouTubeDirectParser.extract_stream_urls(player_response)
    
    target_format = None
    for fmt in formats:
        if str(fmt.get('itag', '')) == str(itag):
            target_format = fmt
            break
    
    # If itag not found, try to find a suitable format
    if not target_format:
        # Look for a progressive format (video+audio)
        for fmt in formats:
            if fmt.get('has_video', False) and fmt.get('has_audio', False):
                target_format = fmt
                break
        
        # If still not found, take the first format
        if not target_format and formats:
            target_format = formats[0]
    
    if not target_format:
        return jsonify({"error": "No suitable format found"}), 404
    
    # Get URL
    url = target_format.get('url', '')
    if not url and 'signatureCipher' in target_format:
        url = YouTubeDirectParser.parse_signature_cipher(target_format['signatureCipher'])
    
    if not url:
        return jsonify({"error": "Could not get stream URL"}), 500
    
    try:
        # Stream with appropriate headers
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(url, headers=headers, stream=True, timeout=TIMEOUT)
        
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                yield chunk
        
        content_type = target_format.get('type', 'video/mp4')
        
        return Response(
            stream_with_context(generate()),
            content_type=content_type,
            headers={
                'Cache-Control': 'no-cache',
                'X-Content-Type-Options': 'nosniff'
            }
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/info')
def get_info():
    """Get video information only"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeDirectParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    player_response = YouTubeDirectParser.get_player_response(video_id)
    if not player_response:
        return jsonify({"error": "Could not get video info"}), 500
    
    video_details = player_response.get('videoDetails', {})
    
    # Get thumbnail URLs
    thumbnails = video_details.get('thumbnail', {}).get('thumbnails', [])
    thumbnail_urls = []
    for thumb in thumbnails:
        thumbnail_urls.append({
            'url': thumb.get('url', ''),
            'width': thumb.get('width', 0),
            'height': thumb.get('height', 0)
        })
    
    return jsonify({
        'success': True,
        'video_id': video_id,
        'title': video_details.get('title', ''),
        'author': video_details.get('author', ''),
        'lengthSeconds': video_details.get('lengthSeconds', 0),
        'viewCount': video_details.get('viewCount', '0'),
        'description': video_details.get('shortDescription', ''),
        'thumbnails': thumbnail_urls,
        'timestamp': time.time()
    })

@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        'status': 'healthy',
        'timestamp': time.time(),
        'service': 'YouTube Direct Parser'
    })

@app.route('/test/<video_id>')
def test_endpoint(video_id):
    """Test endpoint for debugging"""
    player_response = YouTubeDirectParser.get_player_response(video_id)
    
    if player_response:
        streaming_data = player_response.get('streamingData', {})
        formats_count = len(streaming_data.get('formats', [])) + len(streaming_data.get('adaptiveFormats', []))
        
        return jsonify({
            'success': True,
            'video_id': video_id,
            'has_player_response': True,
            'has_streaming_data': 'streamingData' in player_response,
            'formats_count': formats_count,
            'video_title': player_response.get('videoDetails', {}).get('title', 'Unknown'),
            'timestamp': time.time()
        })
    else:
        return jsonify({
            'success': False,
            'error': 'No player response',
            'video_id': video_id
        }), 500

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
    print(f"Starting YouTube Direct Parser on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
