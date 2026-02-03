import os
import re
import json
import time
import requests
from flask import Flask, request, jsonify, Response, stream_with_context, render_template_string
from flask_cors import CORS
from urllib.parse import parse_qs, unquote, quote, urlencode
import base64

app = Flask(__name__)
CORS(app)

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
TIMEOUT = 60

class YouTubeUniversalParser:
    """Universal YouTube Parser for all video types"""
    
    @staticmethod
    def extract_video_id(url):
        """Extract video ID from any YouTube URL"""
        url = str(url).strip()
        
        # Remove query parameters
        url = url.split('?')[0]
        
        # Direct video ID
        if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
            return url
        
        patterns = [
            # Regular videos
            r'youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})',
            r'youtu\.be/([a-zA-Z0-9_-]{11})',
            r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
            # Shorts
            r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
            r'youtu\.be/shorts/([a-zA-Z0-9_-]{11})',
            # Live streams
            r'youtube\.com/live/([a-zA-Z0-9_-]{11})',
            # Mobile
            r'm\.youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})',
            # Alternative domains
            r'youtube-nocookie\.com/embed/([a-zA-Z0-9_-]{11})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    @staticmethod
    def fetch_with_proxy(url):
        """Fetch YouTube page with proxy if needed"""
        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
        
        # Try multiple URLs for shorts
        video_id = YouTubeUniversalParser.extract_video_id(url)
        
        urls_to_try = [
            # Regular watch page
            f"https://www.youtube.com/watch?v={video_id}",
            # Shorts page (for shorts)
            f"https://www.youtube.com/shorts/{video_id}",
            # Embed page
            f"https://www.youtube.com/embed/{video_id}",
            # No-cookie version
            f"https://www.youtube-nocookie.com/embed/{video_id}"
        ]
        
        for try_url in urls_to_try:
            try:
                print(f"Trying URL: {try_url}")
                response = requests.get(try_url, headers=headers, timeout=TIMEOUT)
                
                if response.status_code == 200:
                    print(f"Success with URL: {try_url}")
                    return response.text
                elif response.status_code == 429:  # Rate limited
                    time.sleep(2)
                
            except Exception as e:
                print(f"Failed to fetch {try_url}: {e}")
                continue
        
        return None
    
    @staticmethod
    def extract_json_data(html, pattern_name):
        """Extract JSON data from HTML using various patterns"""
        patterns = {
            'player_response': [
                r'var ytInitialPlayerResponse\s*=\s*({.*?});',
                r'ytInitialPlayerResponse\s*=\s*({.*?});',
                r'window\["ytInitialPlayerResponse"\]\s*=\s*({.*?});',
                r'player_response":"({.*?})"',
                r'"playerResponse":"({.*?})"',
                r'ytInitialPlayerResponse\s*=\s*({.*?})\s*</script>'
            ],
            'initial_data': [
                r'var ytInitialData\s*=\s*({.*?});',
                r'ytInitialData\s*=\s*({.*?});',
                r'window\["ytInitialData"\]\s*=\s*({.*?});'
            ]
        }
        
        for pattern in patterns.get(pattern_name, []):
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1)
                    
                    # Clean JSON string
                    json_str = json_str.replace('\\"', '"')
                    json_str = json_str.replace('\\\\', '\\')
                    json_str = json_str.replace('\\n', '')
                    json_str = json_str.replace('\\r', '')
                    json_str = json_str.replace('\\t', '')
                    json_str = json_str.replace('\\u0026', '&')
                    
                    # Try to parse as JSON
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        # Try base64 decoding for player_response
                        if pattern_name == 'player_response' and ('"' in json_str or '{' not in json_str):
                            try:
                                decoded = base64.b64decode(json_str).decode('utf-8', errors='ignore')
                                return json.loads(decoded)
                            except:
                                continue
                
                except Exception as e:
                    print(f"Error parsing {pattern_name}: {e}")
                    continue
        
        return None
    
    @staticmethod
    def extract_video_info_from_html(html, video_id):
        """Extract video information from HTML"""
        info = {
            'video_id': video_id,
            'title': 'Unknown Title',
            'author': 'Unknown Channel',
            'description': '',
            'duration': 0,
            'views': 0,
            'likes': 0,
            'is_live': False,
            'is_shorts': False,
            'is_age_restricted': False,
            'keywords': [],
            'thumbnails': {}
        }
        
        try:
            # Extract from meta tags
            title_match = re.search(r'<meta name="title" content="([^"]+)"', html)
            if title_match:
                info['title'] = title_match.group(1)
            
            # Extract channel
            channel_match = re.search(r'"author":"([^"]+)"', html)
            if channel_match:
                info['author'] = channel_match.group(1)
            
            # Check if it's shorts
            if '/shorts/' in html or 'SHORTS_PLAYER' in html:
                info['is_shorts'] = True
            
            # Check if live
            if 'isLive' in html or 'LIVE_STREAM' in html:
                info['is_live'] = True
            
            # Get player response
            player_response = YouTubeUniversalParser.extract_json_data(html, 'player_response')
            
            if player_response:
                video_details = player_response.get('videoDetails', {})
                
                info.update({
                    'title': video_details.get('title', info['title']),
                    'author': video_details.get('author', info['author']),
                    'description': video_details.get('shortDescription', ''),
                    'duration': int(video_details.get('lengthSeconds', 0)),
                    'views': int(video_details.get('viewCount', 0)),
                    'is_live': video_details.get('isLive', info['is_live']),
                    'is_age_restricted': video_details.get('isAgeRestricted', False),
                    'keywords': video_details.get('keywords', [])
                })
            
            # Extract from initial data
            initial_data = YouTubeUniversalParser.extract_json_data(html, 'initial_data')
            
            if initial_data:
                # Try to find likes
                try:
                    video_actions = YouTubeUniversalParser.find_key(initial_data, 'videoActions')
                    if video_actions:
                        likes = YouTubeUniversalParser.find_key(video_actions, 'likeCount')
                        if likes:
                            info['likes'] = int(likes)
                except:
                    pass
            
        except Exception as e:
            print(f"Error extracting video info: {e}")
        
        return info
    
    @staticmethod
    def extract_streaming_data(html):
        """Extract streaming data from HTML"""
        player_response = YouTubeUniversalParser.extract_json_data(html, 'player_response')
        
        if not player_response:
            return None
        
        streaming_data = player_response.get('streamingData', {})
        
        # If no streaming data, try to extract from alternative sources
        if not streaming_data:
            # Look for direct URLs in HTML
            direct_urls = YouTubeUniversalParser.extract_direct_urls(html)
            if direct_urls:
                streaming_data = {
                    'formats': [{'url': url, 'itag': 'direct'} for url in direct_urls],
                    'adaptiveFormats': []
                }
        
        return streaming_data
    
    @staticmethod
    def extract_direct_urls(html):
        """Extract direct video URLs from HTML"""
        urls = []
        
        patterns = [
            r'"url":"(https://[^"]*googlevideo\.com[^"]*videoplayback[^"]*)"',
            r'src="(https://[^"]*googlevideo\.com[^"]*videoplayback[^"]*)"',
            r'\\"url\\":\\"(https://[^"]*googlevideo\.com[^"]*videoplayback[^"]*)\\"',
            r'https://[^"]*googlevideo\.com[^"]*videoplayback[^"]*[^"\s]*'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html)
            for match in matches:
                url = match.replace('\\/', '/').replace('\\u0026', '&').replace('\\\\"', '"')
                if 'googlevideo.com' in url and 'videoplayback' in url:
                    # Decode URL if it's encoded
                    url = unquote(url)
                    urls.append(url)
        
        # Remove duplicates
        unique_urls = []
        seen = set()
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return unique_urls
    
    @staticmethod
    def parse_formats(streaming_data):
        """Parse all formats from streaming data"""
        formats = []
        
        if not streaming_data:
            return formats
        
        try:
            # Parse adaptive formats
            adaptive_formats = streaming_data.get('adaptiveFormats', [])
            for fmt in adaptive_formats:
                format_info = YouTubeUniversalParser.parse_format(fmt)
                if format_info:
                    formats.append(format_info)
            
            # Parse progressive formats
            progressive_formats = streaming_data.get('formats', [])
            for fmt in progressive_formats:
                format_info = YouTubeUniversalParser.parse_format(fmt)
                if format_info:
                    formats.append(format_info)
            
        except Exception as e:
            print(f"Error parsing formats: {e}")
        
        return formats
    
    @staticmethod
    def parse_format(fmt):
        """Parse individual format"""
        try:
            # Get URL or cipher
            url = fmt.get('url', '')
            cipher = fmt.get('signatureCipher', '')
            
            if not url and cipher:
                url = YouTubeUniversalParser.decode_cipher(cipher)
            
            if not url:
                return None
            
            # Get basic info
            itag = str(fmt.get('itag', ''))
            mime_type = fmt.get('mimeType', '')
            
            # Determine type
            is_audio = 'audio' in mime_type.lower()
            is_video = 'video' in mime_type.lower() or 'mp4' in mime_type.lower()
            
            # Get quality
            quality = fmt.get('qualityLabel', '')
            if not quality:
                if 'height' in fmt:
                    height = fmt['height']
                    if height <= 144:
                        quality = '144p'
                    elif height <= 240:
                        quality = '240p'
                    elif height <= 360:
                        quality = '360p'
                    elif height <= 480:
                        quality = '480p'
                    elif height <= 720:
                        quality = '720p'
                    elif height <= 1080:
                        quality = '1080p'
                    elif height <= 1440:
                        quality = '1440p'
                    elif height <= 2160:
                        quality = '2160p'
                    else:
                        quality = f'{height}p'
                elif 'bitrate' in fmt:
                    bitrate = fmt['bitrate']
                    quality = f'{bitrate//1000}kbps'
                else:
                    quality = 'Unknown'
            
            # Get size
            size_bytes = fmt.get('contentLength', 0)
            if size_bytes:
                try:
                    size_int = int(size_bytes)
                    if size_int >= 1024**3:
                        size = f"{size_int/(1024**3):.1f} GB"
                    elif size_int >= 1024**2:
                        size = f"{size_int/(1024**2):.1f} MB"
                    elif size_int >= 1024:
                        size = f"{size_int/1024:.1f} KB"
                    else:
                        size = f"{size_int} B"
                except:
                    size = "Unknown"
            else:
                size = "Unknown"
            
            return {
                'itag': itag,
                'quality': quality,
                'type': 'audio' if is_audio else 'video',
                'mime_type': mime_type,
                'url': url,
                'size': size,
                'has_audio': is_audio or (is_video and not is_audio),  # Progressive has audio
                'has_video': is_video,
                'is_progressive': is_video and is_audio,
                'width': fmt.get('width', 0),
                'height': fmt.get('height', 0),
                'fps': fmt.get('fps', 0),
                'bitrate': fmt.get('bitrate', 0)
            }
            
        except Exception as e:
            print(f"Error parsing format: {e}")
            return None
    
    @staticmethod
    def decode_cipher(cipher):
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
            
            # Add signature and other parameters
            sp = params.get('sp', 'signature')
            s = params.get('s', '')
            
            if s:
                url += f"&{sp}={s}"
            
            # Add other important parameters
            for key in ['ratebypass', 'mime', 'clen', 'dur', 'lmt', 'mt', 'ip', 'id', 'source', 'requiressl']:
                if key in params:
                    url += f"&{key}={params[key]}"
            
            return url
            
        except:
            return None
    
    @staticmethod
    def find_key(obj, key):
        """Find a key in nested dictionary"""
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for k, v in obj.items():
                result = YouTubeUniversalParser.find_key(v, key)
                if result:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = YouTubeUniversalParser.find_key(item, key)
                if result:
                    return result
        return None
    
    @staticmethod
    def get_video_data(video_url):
        """Get complete video data"""
        video_id = YouTubeUniversalParser.extract_video_id(video_url)
        if not video_id:
            return None
        
        # Fetch HTML
        html = YouTubeUniversalParser.fetch_with_proxy(video_url)
        if not html:
            return None
        
        # Extract info
        info = YouTubeUniversalParser.extract_video_info_from_html(html, video_id)
        
        # Extract streaming data
        streaming_data = YouTubeUniversalParser.extract_streaming_data(html)
        
        # Parse formats
        formats = []
        if streaming_data:
            formats = YouTubeUniversalParser.parse_formats(streaming_data)
        
        # Also extract direct URLs
        direct_urls = YouTubeUniversalParser.extract_direct_urls(html)
        
        # If no formats from streaming data, create from direct URLs
        if not formats and direct_urls:
            for url in direct_urls:
                formats.append({
                    'itag': 'direct',
                    'quality': 'Direct URL',
                    'type': 'video',
                    'mime_type': 'video/mp4',
                    'url': url,
                    'size': 'Unknown',
                    'has_audio': True,
                    'has_video': True,
                    'is_progressive': True
                })
        
        return {
            'video_id': video_id,
            'info': info,
            'formats': formats,
            'direct_urls': direct_urls,
            'html_length': len(html)
        }

# ==================== SIMPLIFIED API ====================

@app.route('/')
def home():
    """Simple home page"""
    return jsonify({
        "api": "YouTube Universal Downloader",
        "version": "1.0",
        "endpoints": {
            "/video/info?url=URL": "Get video information",
            "/video/formats?url=URL": "Get available formats",
            "/video/download?url=URL&quality=QUALITY": "Download video",
            "/health": "Health check"
        },
        "example": "/video/info?url=https://youtube.com/watch?v=dQw4w9WgXcQ"
    })

@app.route('/video/info', methods=['GET'])
def video_info():
    """Get video information"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    try:
        data = YouTubeUniversalParser.get_video_data(url)
        
        if not data:
            return jsonify({"error": "Could not fetch video data"}), 500
        
        info = data['info']
        
        # Format duration
        if info['duration'] > 0:
            minutes = info['duration'] // 60
            seconds = info['duration'] % 60
            info['duration_formatted'] = f"{minutes}:{seconds:02d}"
        else:
            info['duration_formatted'] = "0:00"
        
        # Format views
        if info['views'] >= 1000000:
            info['views_formatted'] = f"{info['views']/1000000:.1f}M"
        elif info['views'] >= 1000:
            info['views_formatted'] = f"{info['views']/1000:.1f}K"
        else:
            info['views_formatted'] = str(info['views'])
        
        # Add thumbnails
        thumbnails = {
            'default': f"https://i.ytimg.com/vi/{data['video_id']}/default.jpg",
            'medium': f"https://i.ytimg.com/vi/{data['video_id']}/mqdefault.jpg",
            'high': f"https://i.ytimg.com/vi/{data['video_id']}/hqdefault.jpg",
            'standard': f"https://i.ytimg.com/vi/{data['video_id']}/sddefault.jpg",
            'maxres': f"https://i.ytimg.com/vi/{data['video_id']}/maxresdefault.jpg"
        }
        info['thumbnails'] = thumbnails
        
        return jsonify({
            "success": True,
            "video_id": data['video_id'],
            "info": info,
            "has_formats": len(data['formats']) > 0,
            "formats_count": len(data['formats']),
            "timestamp": time.time()
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/video/formats', methods=['GET'])
def video_formats():
    """Get available formats"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    try:
        data = YouTubeUniversalParser.get_video_data(url)
        
        if not data:
            return jsonify({"error": "Could not fetch video data"}), 500
        
        if not data['formats']:
            return jsonify({
                "success": False,
                "error": "No formats found. Video might be restricted.",
                "video_id": data['video_id'],
                "direct_urls_available": len(data['direct_urls']) > 0
            }), 404
        
        # Group formats
        video_formats = []
        audio_formats = []
        progressive_formats = []
        
        for fmt in data['formats']:
            if fmt['type'] == 'video' and not fmt['has_audio']:
                video_formats.append(fmt)
            elif fmt['type'] == 'audio':
                audio_formats.append(fmt)
            elif fmt['is_progressive']:
                progressive_formats.append(fmt)
        
        # Add download URLs
        def add_download_urls(formats_list):
            for fmt in formats_list:
                fmt['download_url'] = f"/video/download?url={quote(url)}&itag={fmt['itag']}"
                fmt['stream_url'] = f"/video/stream?url={quote(url)}&itag={fmt['itag']}"
        
        add_download_urls(video_formats)
        add_download_urls(audio_formats)
        add_download_urls(progressive_formats)
        
        # Sort by quality
        def sort_by_quality(formats_list):
            return sorted(formats_list, key=lambda x: (
                0 if 'p' in x['quality'] else 1,
                -int(re.search(r'\d+', x['quality']).group()) if re.search(r'\d+', x['quality']) else 0
            ))
        
        video_formats = sort_by_quality(video_formats)
        audio_formats = sort_by_quality(audio_formats)
        progressive_formats = sort_by_quality(progressive_formats)
        
        return jsonify({
            "success": True,
            "video_id": data['video_id'],
            "title": data['info']['title'],
            "author": data['info']['author'],
            "is_shorts": data['info']['is_shorts'],
            "is_live": data['info']['is_live'],
            "formats": {
                "video_only": video_formats[:10],  # Limit to 10 each
                "audio_only": audio_formats[:10],
                "progressive": progressive_formats[:10]
            },
            "counts": {
                "total": len(data['formats']),
                "video_only": len(video_formats),
                "audio_only": len(audio_formats),
                "progressive": len(progressive_formats)
            },
            "recommended": {
                "best_video": video_formats[0] if video_formats else None,
                "best_audio": audio_formats[0] if audio_formats else None,
                "best_progressive": progressive_formats[0] if progressive_formats else None
            },
            "timestamp": time.time()
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/video/download', methods=['GET'])
def video_download():
    """Download video"""
    url = request.args.get('url', '')
    itag = request.args.get('itag', '')
    quality = request.args.get('quality', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    try:
        data = YouTubeUniversalParser.get_video_data(url)
        
        if not data or not data['formats']:
            return jsonify({"error": "No formats available"}), 404
        
        # Find the requested format
        target_format = None
        
        if itag:
            for fmt in data['formats']:
                if str(fmt.get('itag', '')) == str(itag):
                    target_format = fmt
                    break
        
        elif quality:
            for fmt in data['formats']:
                if quality.lower() in fmt.get('quality', '').lower():
                    target_format = fmt
                    break
        
        # Default to first progressive or first available
        if not target_format:
            for fmt in data['formats']:
                if fmt.get('is_progressive', False):
                    target_format = fmt
                    break
            
            if not target_format and data['formats']:
                target_format = data['formats'][0]
        
        if not target_format or not target_format.get('url'):
            return jsonify({
                "error": "Format not found",
                "available_formats": [
                    f"{fmt.get('quality')} (itag: {fmt.get('itag')})" 
                    for fmt in data['formats'][:5]
                ]
            }), 404
        
        download_url = target_format['url']
        
        # Generate filename
        title = data['info']['title']
        filename = re.sub(r'[^\w\-_\. ]', '_', title[:50])
        
        if target_format['type'] == 'audio':
            filename += f"_{target_format['quality']}.mp3"
            content_type = 'audio/mpeg'
        else:
            filename += f"_{target_format['quality']}.mp4"
            content_type = target_format.get('mime_type', 'video/mp4')
        
        # Stream download
        headers = {'User-Agent': USER_AGENT}
        
        def generate():
            with requests.get(download_url, headers=headers, stream=True, timeout=TIMEOUT) as r:
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

@app.route('/video/stream', methods=['GET'])
def video_stream():
    """Stream video"""
    url = request.args.get('url', '')
    itag = request.args.get('itag', '18')  # Default 360p
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    try:
        data = YouTubeUniversalParser.get_video_data(url)
        
        if not data or not data['formats']:
            return jsonify({"error": "No formats available"}), 404
        
        # Find format
        target_format = None
        for fmt in data['formats']:
            if str(fmt.get('itag', '')) == str(itag):
                target_format = fmt
                break
        
        if not target_format:
            # Find any progressive format
            for fmt in data['formats']:
                if fmt.get('is_progressive', False):
                    target_format = fmt
                    break
        
        if not target_format or not target_format.get('url'):
            return jsonify({"error": "Stream format not found"}), 404
        
        stream_url = target_format['url']
        
        # Stream
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(stream_url, headers=headers, stream=True, timeout=TIMEOUT)
        
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                yield chunk
        
        return Response(
            stream_with_context(generate()),
            content_type=target_format.get('mime_type', 'video/mp4')
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/video/direct', methods=['GET'])
def video_direct():
    """Get direct download URL"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    try:
        data = YouTubeUniversalParser.get_video_data(url)
        
        if not data:
            return jsonify({"error": "Could not fetch video"}), 500
        
        # Return first available URL
        if data['direct_urls']:
            return jsonify({
                "success": True,
                "video_id": data['video_id'],
                "direct_url": data['direct_urls'][0],
                "url_count": len(data['direct_urls']),
                "note": "Use this URL directly in browser or download manager"
            })
        elif data['formats']:
            return jsonify({
                "success": True,
                "video_id": data['video_id'],
                "direct_url": data['formats'][0]['url'],
                "quality": data['formats'][0]['quality'],
                "note": "Format-specific URL"
            })
        else:
            return jsonify({"error": "No URLs found"}), 404
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "service": "YouTube Universal Downloader"
    })

@app.route('/test/<video_id>')
def test_video(video_id):
    """Test endpoint for debugging"""
    url = f"https://youtube.com/watch?v={video_id}"
    
    try:
        data = YouTubeUniversalParser.get_video_data(url)
        
        if data:
            return jsonify({
                "success": True,
                "video_id": video_id,
                "title": data['info']['title'],
                "author": data['info']['author'],
                "is_shorts": data['info']['is_shorts'],
                "formats_count": len(data['formats']),
                "direct_urls_count": len(data['direct_urls']),
                "sample_format": data['formats'][0] if data['formats'] else None,
                "sample_direct_url": data['direct_urls'][0] if data['direct_urls'] else None,
                "html_length": data['html_length']
            })
        else:
            return jsonify({
                "success": False,
                "error": "No data retrieved",
                "video_id": video_id
            }), 500
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting YouTube Universal Downloader on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
