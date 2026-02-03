import os
import re
import json
import time
import requests
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from urllib.parse import parse_qs, unquote, quote, urlencode
import base64
import html

app = Flask(__name__)
CORS(app)

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
TIMEOUT = 30

class YouTubeAdvancedParser:
    """Advanced YouTube parser with multiple extraction methods"""
    
    @staticmethod
    def extract_video_id(url):
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
    def method1_get_player_response(video_id):
        """Method 1: Extract from watch page"""
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {'User-Agent': USER_AGENT}
            
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            if response.status_code != 200:
                return None
            
            html_content = response.text
            
            # Pattern 1: ytInitialPlayerResponse
            patterns = [
                r'var ytInitialPlayerResponse\s*=\s*({.*?});',
                r'ytInitialPlayerResponse\s*=\s*({.*?});',
                r'window\["ytInitialPlayerResponse"\]\s*=\s*({.*?});'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, html_content, re.DOTALL)
                if match:
                    try:
                        json_str = match.group(1)
                        # Clean JSON string
                        json_str = json_str.replace('\\"', '"')
                        json_str = json_str.replace('\\\\', '\\')
                        json_str = json_str.replace('\n', '')
                        json_str = json_str.replace('\r', '')
                        
                        data = json.loads(json_str)
                        return data
                    except:
                        continue
            
            # Pattern 2: Look for player_response in script tags
            script_pattern = r'<script[^>]*>.*?var ytInitialPlayerResponse\s*=\s*({.*?});.*?</script>'
            match = re.search(script_pattern, html_content, re.DOTALL | re.IGNORECASE)
            if match:
                try:
                    json_str = match.group(1)
                    data = json.loads(json_str)
                    return data
                except:
                    pass
            
            return None
            
        except Exception as e:
            print(f"Method 1 error: {e}")
            return None
    
    @staticmethod
    def method2_get_embed_page(video_id):
        """Method 2: Extract from embed page"""
        try:
            url = f"https://www.youtube.com/embed/{video_id}"
            headers = {'User-Agent': USER_AGENT}
            
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            if response.status_code != 200:
                return None
            
            html_content = response.text
            
            # Look for player config in embed page
            pattern = r'yt\.setConfig\(\s*{\s*\'PLAYER_CONFIG\'\s*:\s*({.*?})\s*}\s*\);'
            match = re.search(pattern, html_content, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1).replace("'", '"')
                    data = json.loads(json_str)
                    return data
                except:
                    pass
            
            # Look for args in embed page
            pattern = r'"args"\s*:\s*({[^}]+})'
            match = re.search(pattern, html_content)
            if match:
                try:
                    json_str = match.group(1)
                    data = json.loads(json_str)
                    return {'args': data}
                except:
                    pass
            
            return None
            
        except Exception as e:
            print(f"Method 2 error: {e}")
            return None
    
    @staticmethod
    def method3_get_player_api(video_id):
        """Method 3: Use YouTube player API"""
        try:
            # Try to get player API response
            url = f"https://www.youtube.com/youtubei/v1/player"
            headers = {
                'User-Agent': USER_AGENT,
                'Content-Type': 'application/json',
                'Accept': '*/*',
                'Origin': 'https://www.youtube.com',
                'Referer': f'https://www.youtube.com/watch?v={video_id}'
            }
            
            # YouTube's client payload
            payload = {
                "context": {
                    "client": {
                        "hl": "en",
                        "clientName": "WEB",
                        "clientVersion": "2.20231219.01.00",
                        "platform": "DESKTOP"
                    }
                },
                "videoId": video_id,
                "playbackContext": {
                    "contentPlaybackContext": {
                        "html5Preference": "HTML5_PREF_WANTS"
                    }
                },
                "contentCheckOk": True,
                "racyCheckOk": True
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
            if response.status_code == 200:
                return response.json()
            
            return None
            
        except Exception as e:
            print(f"Method 3 error: {e}")
            return None
    
    @staticmethod
    def method4_direct_pattern_search(video_id):
        """Method 4: Direct pattern search in HTML"""
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {'User-Agent': USER_AGENT}
            
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            if response.status_code != 200:
                return None
            
            html_content = response.text
            
            # Look for streaming URLs directly
            patterns = [
                r'"url":"(https://[^"]*googlevideo\.com[^"]*videoplayback[^"]*)"',
                r'src="(https://[^"]*googlevideo\.com[^"]*videoplayback[^"]*)"',
                r'"(https://rr[^"]*googlevideo\.com[^"]*videoplayback[^"]*)"'
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, html_content)
                for match in matches:
                    url = match.replace('\\/', '/').replace('\\u0026', '&')
                    if 'itag=' in url and 'key=' in url:
                        return {'direct_url': url}
            
            return None
            
        except Exception as e:
            print(f"Method 4 error: {e}")
            return None
    
    @staticmethod
    def get_player_response(video_id):
        """Try all methods to get player response"""
        methods = [
            YouTubeAdvancedParser.method1_get_player_response,
            YouTubeAdvancedParser.method3_get_player_api,
            YouTubeAdvancedParser.method2_get_embed_page,
            YouTubeAdvancedParser.method4_direct_pattern_search
        ]
        
        for method in methods:
            result = method(video_id)
            if result:
                print(f"Success with method: {method.__name__}")
                return result
        
        return None
    
    @staticmethod
    def extract_streaming_data(player_response):
        """Extract streaming data from player response"""
        try:
            if not player_response:
                return []
            
            # Different response structures
            streaming_data = None
            
            # Structure 1: Direct streamingData
            if 'streamingData' in player_response:
                streaming_data = player_response['streamingData']
            
            # Structure 2: In videoDetails
            elif 'videoDetails' in player_response and 'streamingData' in player_response['videoDetails']:
                streaming_data = player_response['videoDetails']['streamingData']
            
            # Structure 3: In args (old method)
            elif 'args' in player_response and 'url_encoded_fmt_stream_map' in player_response['args']:
                return YouTubeAdvancedParser.parse_old_format(player_response['args'])
            
            # Structure 4: Direct URL
            elif 'direct_url' in player_response:
                return [{
                    'url': player_response['direct_url'],
                    'quality': 'Unknown',
                    'type': 'video/mp4',
                    'itag': 'unknown'
                }]
            
            if not streaming_data:
                return []
            
            formats = []
            
            # Parse adaptive formats
            if 'adaptiveFormats' in streaming_data:
                for fmt in streaming_data['adaptiveFormats']:
                    if 'url' in fmt:
                        formats.append(YouTubeAdvancedParser.parse_format(fmt))
                    elif 'signatureCipher' in fmt:
                        url = YouTubeAdvancedParser.decode_signature_cipher(fmt['signatureCipher'])
                        if url:
                            fmt['url'] = url
                            formats.append(YouTubeAdvancedParser.parse_format(fmt))
            
            # Parse progressive formats
            if 'formats' in streaming_data:
                for fmt in streaming_data['formats']:
                    if 'url' in fmt:
                        formats.append(YouTubeAdvancedParser.parse_format(fmt))
                    elif 'signatureCipher' in fmt:
                        url = YouTubeAdvancedParser.decode_signature_cipher(fmt['signatureCipher'])
                        if url:
                            fmt['url'] = url
                            formats.append(YouTubeAdvancedParser.parse_format(fmt))
            
            return formats
            
        except Exception as e:
            print(f"Error extracting streaming data: {e}")
            return []
    
    @staticmethod
    def parse_format(fmt):
        """Parse individual format"""
        quality = fmt.get('qualityLabel', '')
        if not quality:
            if 'height' in fmt:
                quality = f"{fmt['height']}p"
            elif 'bitrate' in fmt:
                quality = f"{fmt['bitrate'] // 1000}kbps"
            else:
                quality = "Unknown"
        
        # Determine if it's audio or video
        mime_type = fmt.get('mimeType', '')
        is_audio = 'audio' in mime_type.lower()
        is_video = 'video' in mime_type.lower() or 'mp4' in mime_type.lower()
        
        # Get file size
        size = fmt.get('contentLength', '0')
        if size and size != '0':
            try:
                size_int = int(size)
                if size_int > 1024*1024:
                    size_str = f"{size_int/(1024*1024):.1f} MB"
                elif size_int > 1024:
                    size_str = f"{size_int/1024:.1f} KB"
                else:
                    size_str = f"{size_int} B"
            except:
                size_str = "Unknown"
        else:
            size_str = "Unknown"
        
        return {
            'itag': str(fmt.get('itag', '')),
            'quality': quality,
            'type': mime_type,
            'url': fmt.get('url', ''),
            'has_video': is_video,
            'has_audio': is_audio or (is_video and not is_audio),  # Progressive has both
            'size': size_str,
            'fps': fmt.get('fps', '')
        }
    
    @staticmethod
    def parse_old_format(args):
        """Parse old format URL encoded stream map"""
        try:
            stream_map = args.get('url_encoded_fmt_stream_map', '')
            if not stream_map:
                return []
            
            formats = []
            streams = stream_map.split(',')
            
            for stream in streams:
                params = {}
                for param in stream.split('&'):
                    if '=' in param:
                        key, value = param.split('=', 1)
                        params[key] = unquote(value)
                
                if 'url' in params:
                    quality = params.get('quality', 'Unknown')
                    itag = params.get('itag', '')
                    
                    # Add signature if present
                    url = params['url']
                    if 'sig' in params:
                        url += f"&signature={params['sig']}"
                    elif 's' in params:
                        url += f"&signature={params['s']}"
                    
                    formats.append({
                        'itag': itag,
                        'quality': quality,
                        'type': params.get('type', 'video/mp4'),
                        'url': url,
                        'has_video': True,
                        'has_audio': 'audio' not in quality.lower(),
                        'size': 'Unknown'
                    })
            
            return formats
            
        except Exception as e:
            print(f"Error parsing old format: {e}")
            return []
    
    @staticmethod
    def decode_signature_cipher(cipher):
        """Decode signatureCipher to get URL"""
        try:
            params = {}
            for param in cipher.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    params[key] = unquote(value)
            
            url = params.get('url', '')
            if not url:
                return None
            
            # Add signature parameters
            sp = params.get('sp', 'signature')
            s = params.get('s', '')
            
            if s:
                # For now, just append the signature
                # In production, you might need to decode/transform it
                url += f"&{sp}={s}"
            
            return url
            
        except:
            return None
    
    @staticmethod
    def get_video_info(video_id):
        """Get video information"""
        try:
            # Try oEmbed first
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            headers = {'User-Agent': USER_AGENT}
            
            response = requests.get(oembed_url, headers=headers, timeout=TIMEOUT)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "title": data.get("title", ""),
                    "author": data.get("author_name", ""),
                    "thumbnail": data.get("thumbnail_url", ""),
                    "success": True
                }
        except:
            pass
        
        # Fallback: Scrape from page
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {'User-Agent': USER_AGENT}
            
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            
            if response.status_code == 200:
                html_content = response.text
                
                # Extract title
                title = "Unknown Title"
                title_match = re.search(r'<meta name="title" content="([^"]+)"', html_content)
                if title_match:
                    title = title_match.group(1)
                
                # Extract channel
                channel = "Unknown Channel"
                channel_match = re.search(r'"author":"([^"]+)"', html_content)
                if channel_match:
                    channel = channel_match.group(1)
                
                return {
                    "title": title,
                    "author": channel,
                    "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                    "success": True
                }
        except:
            pass
        
        return {"title": "", "author": "", "thumbnail": "", "success": False}

# ==================== ROUTES ====================

@app.route('/')
def home():
    return jsonify({
        "api": "YouTube Advanced Parser",
        "version": "2.0",
        "methods": "4 different extraction methods",
        "endpoints": {
            "/extract?url=YOUTUBE_URL": "Extract video links",
            "/download/VIDEO_ID?itag=ITAG": "Download video",
            "/play/VIDEO_ID?itag=ITAG": "Play/stream video",
            "/test/VIDEO_ID": "Test extraction",
            "/health": "Health check"
        },
        "note": "Direct YouTube parsing without external APIs"
    })

@app.route('/extract')
def extract():
    """Extract video links"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeAdvancedParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Get video info
    info = YouTubeAdvancedParser.get_video_info(video_id)
    
    # Get player response using multiple methods
    player_response = YouTubeAdvancedParser.get_player_response(video_id)
    
    if not player_response:
        return jsonify({
            "success": False,
            "error": "Could not extract video data",
            "video_id": video_id,
            "methods_tried": 4,
            "note": "YouTube might have changed their structure"
        }), 500
    
    # Extract streaming formats
    formats = YouTubeAdvancedParser.extract_streaming_data(player_response)
    
    # Filter only valid formats with URLs
    valid_formats = []
    for fmt in formats:
        if fmt.get('url'):
            # Add download endpoint
            fmt['download_url'] = f"/download/{video_id}?itag={fmt['itag']}"
            fmt['play_url'] = f"/play/{video_id}?itag={fmt['itag']}"
            valid_formats.append(fmt)
    
    # Group by type
    video_formats = [f for f in valid_formats if f['has_video'] and f['has_audio']]
    audio_only = [f for f in valid_formats if f['has_audio'] and not f['has_video']]
    video_only = [f for f in valid_formats if f['has_video'] and not f['has_audio']]
    
    return jsonify({
        "success": True,
        "video_id": video_id,
        "title": info.get("title", ""),
        "author": info.get("author", ""),
        "thumbnail": info.get("thumbnail", ""),
        "formats": {
            "video_with_audio": video_formats,
            "audio_only": audio_only,
            "video_only": video_only
        },
        "counts": {
            "total": len(valid_formats),
            "video_with_audio": len(video_formats),
            "audio_only": len(audio_only),
            "video_only": len(video_only)
        },
        "timestamp": time.time(),
        "note": "Use download_url or play_url to access the content"
    })

@app.route('/download/<video_id>')
def download(video_id):
    """Download video"""
    itag = request.args.get('itag', '')
    
    if not itag:
        return jsonify({"error": "itag parameter is required"}), 400
    
    # Get player response
    player_response = YouTubeAdvancedParser.get_player_response(video_id)
    if not player_response:
        return jsonify({"error": "Could not get video data"}), 500
    
    # Extract formats and find the right one
    formats = YouTubeAdvancedParser.extract_streaming_data(player_response)
    
    target_format = None
    for fmt in formats:
        if str(fmt.get('itag', '')) == str(itag) and fmt.get('url'):
            target_format = fmt
            break
    
    if not target_format:
        return jsonify({"error": "Format not found or no URL available"}), 404
    
    url = target_format['url']
    
    try:
        # Get video info for filename
        info = YouTubeAdvancedParser.get_video_info(video_id)
        title = info.get('title', f'video_{video_id}')
        
        # Clean filename
        filename = re.sub(r'[^\w\-_\. ]', '_', title[:50])
        
        # Add quality and extension
        if target_format['has_audio'] and not target_format['has_video']:
            filename += f"_audio_{itag}.mp3"
            content_type = 'audio/mpeg'
        else:
            filename += f"_{target_format.get('quality', 'video')}_{itag}.mp4"
            content_type = target_format.get('type', 'video/mp4')
        
        # Stream the download
        headers = {'User-Agent': USER_AGENT}
        
        def generate():
            with requests.get(url, headers=headers, stream=True, timeout=TIMEOUT) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=8192):
                    yield chunk
        
        return Response(
            stream_with_context(generate()),
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': content_type
            }
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/play/<video_id>')
def play(video_id):
    """Play/stream video"""
    itag = request.args.get('itag', '')
    
    # Get player response
    player_response = YouTubeAdvancedParser.get_player_response(video_id)
    if not player_response:
        return jsonify({"error": "Could not get video data"}), 500
    
    # Extract formats
    formats = YouTubeAdvancedParser.extract_streaming_data(player_response)
    
    # Find format
    target_format = None
    if itag:
        for fmt in formats:
            if str(fmt.get('itag', '')) == str(itag) and fmt.get('url'):
                target_format = fmt
                break
    
    # If no itag specified or not found, find a suitable format
    if not target_format:
        # Look for a progressive format first
        for fmt in formats:
            if fmt.get('has_video') and fmt.get('has_audio') and fmt.get('url'):
                target_format = fmt
                break
        
        # Then look for any format
        if not target_format and formats:
            for fmt in formats:
                if fmt.get('url'):
                    target_format = fmt
                    break
    
    if not target_format or not target_format.get('url'):
        return jsonify({"error": "No playable format found"}), 404
    
    url = target_format['url']
    
    try:
        # Stream the video
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
                'Accept-Ranges': 'bytes'
            }
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/test/<video_id>')
def test(video_id):
    """Test endpoint to see what's available"""
    # Try all methods
    method1 = YouTubeAdvancedParser.method1_get_player_response(video_id)
    method2 = YouTubeAdvancedParser.method2_get_embed_page(video_id)
    method3 = YouTubeAdvancedParser.method3_get_player_api(video_id)
    method4 = YouTubeAdvancedParser.method4_direct_pattern_search(video_id)
    
    # Get video info
    info = YouTubeAdvancedParser.get_video_info(video_id)
    
    # Try to extract formats from first successful method
    player_response = None
    successful_method = None
    
    if method1:
        player_response = method1
        successful_method = "method1_get_player_response"
    elif method3:
        player_response = method3
        successful_method = "method3_get_player_api"
    elif method2:
        player_response = method2
        successful_method = "method2_get_embed_page"
    elif method4:
        player_response = method4
        successful_method = "method4_direct_pattern_search"
    
    formats = []
    if player_response:
        formats = YouTubeAdvancedParser.extract_streaming_data(player_response)
    
    return jsonify({
        "video_id": video_id,
        "title": info.get("title", ""),
        "author": info.get("author", ""),
        "methods": {
            "method1": bool(method1),
            "method2": bool(method2),
            "method3": bool(method3),
            "method4": bool(method4)
        },
        "successful_method": successful_method,
        "formats_count": len(formats),
        "has_formats_with_urls": any(f.get('url') for f in formats),
        "available_formats": [f['quality'] for f in formats if f.get('url')],
        "sample_format": formats[0] if formats else None,
        "timestamp": time.time()
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "service": "YouTube Advanced Parser"
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting YouTube Advanced Parser on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
