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

# Configuration
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
TIMEOUT = 60

class YouTubeMasterParser:
    """Master YouTube Parser for all video/audio qualities"""
    
    # YouTube quality mapping
    QUALITY_MAP = {
        '144': '144p',
        '240': '240p', 
        '360': '360p',
        '480': '480p',
        '720': '720p (HD)',
        '1080': '1080p (FHD)',
        '1440': '1440p (2K)',
        '2160': '2160p (4K)',
        '4320': '4320p (8K)'
    }
    
    AUDIO_QUALITY_MAP = {
        '50': '48kbps',
        '70': '64kbps',
        '140': '128kbps',
        '141': '256kbps',
        '251': '160kbps (opus)',
        '171': '128kbps (opus)'
    }
    
    @staticmethod
    def extract_video_id(url):
        """Extract video ID from any YouTube URL format"""
        url = str(url).strip()
        
        # Direct video ID
        if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
            return url
        
        patterns = [
            r'(?:youtube\.com\/watch\?v=)([a-zA-Z0-9_-]{11})',
            r'(?:youtu\.be\/)([a-zA-Z0-9_-]{11})',
            r'(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
            r'(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})',
            r'(?:youtube\.com\/live\/)([a-zA-Z0-9_-]{11})',
            r'(?:youtube\.com\/v\/)([a-zA-Z0-9_-]{11})',
            r'(?:m\.youtube\.com\/watch\?v=)([a-zA-Z0-9_-]{11})',
            r'(?:youtube\.com\/watch\?.*v=)([a-zA-Z0-9_-]{11})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    @staticmethod
    def fetch_with_retry(url, retries=3):
        """Fetch with retry mechanism"""
        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'no-cache'
        }
        
        for attempt in range(retries):
            try:
                response = requests.get(url, headers=headers, timeout=TIMEOUT)
                if response.status_code == 200:
                    return response.text
                elif response.status_code == 429:  # Rate limited
                    time.sleep(2 ** attempt)  # Exponential backoff
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(1)
                else:
                    raise
        
        return None
    
    @staticmethod
    def get_video_page(video_id):
        """Get YouTube video page HTML"""
        url = f"https://www.youtube.com/watch?v={video_id}"
        return YouTubeMasterParser.fetch_with_retry(url)
    
    @staticmethod
    def get_embed_page(video_id):
        """Get YouTube embed page HTML"""
        url = f"https://www.youtube.com/embed/{video_id}"
        return YouTubeMasterParser.fetch_with_retry(url)
    
    @staticmethod
    def extract_all_data(html):
        """Extract all possible data from YouTube HTML"""
        data = {
            'player_response': None,
            'initial_data': None,
            'streaming_data': None,
            'video_details': None,
            'direct_urls': [],
            'captions': [],
            'keywords': [],
            'thumbnails': []
        }
        
        try:
            # Extract player response
            patterns = [
                r'var ytInitialPlayerResponse\s*=\s*({.*?});',
                r'ytInitialPlayerResponse\s*=\s*({.*?});',
                r'window\["ytInitialPlayerResponse"\]\s*=\s*({.*?});'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, html, re.DOTALL)
                if match:
                    try:
                        json_str = match.group(1)
                        # Clean JSON
                        json_str = json_str.replace('\\"', '"')
                        json_str = json_str.replace('\\\\', '\\')
                        json_str = json_str.replace('\n', ' ')
                        data['player_response'] = json.loads(json_str)
                        break
                    except:
                        continue
            
            # Extract initial data
            patterns = [
                r'var ytInitialData\s*=\s*({.*?});',
                r'ytInitialData\s*=\s*({.*?});',
                r'window\["ytInitialData"\]\s*=\s*({.*?});'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, html, re.DOTALL)
                if match:
                    try:
                        json_str = match.group(1)
                        json_str = json_str.replace('\\"', '"')
                        json_str = json_str.replace('\\\\', '\\')
                        data['initial_data'] = json.loads(json_str)
                        break
                    except:
                        continue
            
            # Extract streaming data from player response
            if data['player_response']:
                data['streaming_data'] = data['player_response'].get('streamingData', {})
                data['video_details'] = data['player_response'].get('videoDetails', {})
            
            # Extract direct URLs
            url_patterns = [
                r'"url":"(https://[^"]*googlevideo\.com[^"]*videoplayback[^"]*)"',
                r'src="(https://[^"]*googlevideo\.com[^"]*videoplayback[^"]*)"',
                r'\\"url\\":\\"(https://[^"]*googlevideo\.com[^"]*videoplayback[^"]*)\\"'
            ]
            
            for pattern in url_patterns:
                matches = re.findall(pattern, html)
                for match in matches:
                    url = match.replace('\\/', '/').replace('\\u0026', '&')
                    if 'googlevideo.com' in url and 'videoplayback' in url:
                        data['direct_urls'].append(url)
            
            # Extract captions
            caption_pattern = r'"captionTracks":\[(.*?)\]'
            match = re.search(caption_pattern, html)
            if match:
                try:
                    captions_json = '[' + match.group(1) + ']'
                    captions_json = captions_json.replace('\\"', '"')
                    data['captions'] = json.loads(captions_json)
                except:
                    pass
            
            # Extract keywords
            if data['video_details']:
                data['keywords'] = data['video_details'].get('keywords', [])
            
            # Extract thumbnails
            if data['video_details'] and 'thumbnail' in data['video_details']:
                data['thumbnails'] = data['video_details']['thumbnail'].get('thumbnails', [])
            
        except Exception as e:
            print(f"Error extracting data: {e}")
        
        return data
    
    @staticmethod
    def parse_all_formats(streaming_data):
        """Parse all available formats from streaming data"""
        formats = []
        
        if not streaming_data:
            return formats
        
        try:
            # Parse adaptive formats (video + audio separate)
            adaptive_formats = streaming_data.get('adaptiveFormats', [])
            for fmt in adaptive_formats:
                format_info = YouTubeMasterParser.parse_format(fmt)
                if format_info:
                    formats.append(format_info)
            
            # Parse progressive formats (video + audio together)
            progressive_formats = streaming_data.get('formats', [])
            for fmt in progressive_formats:
                format_info = YouTubeMasterParser.parse_format(fmt)
                if format_info:
                    formats.append(format_info)
            
            # Sort formats by quality
            formats.sort(key=lambda x: (
                0 if x['type'] == 'video' else 1,
                -int(re.search(r'\d+', x['quality']).group()) if re.search(r'\d+', x['quality']) else 0
            ))
            
        except Exception as e:
            print(f"Error parsing formats: {e}")
        
        return formats
    
    @staticmethod
    def parse_format(fmt):
        """Parse individual format"""
        try:
            # Get URL
            url = fmt.get('url', '')
            if not url and 'signatureCipher' in fmt:
                url = YouTubeMasterParser.decode_cipher(fmt['signatureCipher'])
            
            if not url:
                return None
            
            # Get itag
            itag = str(fmt.get('itag', ''))
            
            # Determine format type
            mime_type = fmt.get('mimeType', '')
            is_audio = 'audio' in mime_type.lower()
            is_video = 'video' in mime_type.lower() or 'mp4' in mime_type.lower()
            
            # Get quality label
            quality_label = fmt.get('qualityLabel', '')
            
            if is_video:
                # Video format
                if quality_label:
                    quality = quality_label
                elif 'height' in fmt:
                    height = fmt['height']
                    quality = YouTubeMasterParser.QUALITY_MAP.get(str(height), f"{height}p")
                else:
                    quality = "Unknown"
                
                fps = fmt.get('fps', 30)
                if fps > 30:
                    quality += f" ({fps}fps)"
                
                format_type = 'video'
                
            elif is_audio:
                # Audio format
                bitrate = fmt.get('bitrate', 0)
                if itag in YouTubeMasterParser.AUDIO_QUALITY_MAP:
                    quality = YouTubeMasterParser.AUDIO_QUALITY_MAP[itag]
                elif bitrate:
                    quality = f"{bitrate//1000}kbps"
                else:
                    quality = "Unknown"
                
                format_type = 'audio'
                
            else:
                # Unknown format
                quality = "Unknown"
                format_type = 'unknown'
            
            # Get codec
            codec = fmt.get('codecs', 'Unknown')
            if isinstance(codec, list):
                codec = ', '.join(codec)
            
            # Get approximate size
            content_length = fmt.get('contentLength', '0')
            try:
                size_bytes = int(content_length)
                if size_bytes == 0:
                    size = "Unknown"
                elif size_bytes >= 1024**3:  # GB
                    size = f"{size_bytes/(1024**3):.1f} GB"
                elif size_bytes >= 1024**2:  # MB
                    size = f"{size_bytes/(1024**2):.1f} MB"
                elif size_bytes >= 1024:  # KB
                    size = f"{size_bytes/1024:.1f} KB"
                else:
                    size = f"{size_bytes} B"
            except:
                size = "Unknown"
            
            # Get audio channels
            audio_channels = fmt.get('audioChannels', 2)
            
            return {
                'itag': itag,
                'type': format_type,
                'quality': quality,
                'mime_type': mime_type,
                'codec': codec,
                'url': url,
                'size': size,
                'bitrate': fmt.get('bitrate', 0),
                'fps': fmt.get('fps', 0),
                'width': fmt.get('width', 0),
                'height': fmt.get('height', 0),
                'audio_channels': audio_channels,
                'is_progressive': 'progressive' in mime_type.lower() or (is_video and is_audio),
                'has_audio': is_audio,
                'has_video': is_video
            }
            
        except Exception as e:
            print(f"Error parsing format: {e}")
            return None
    
    @staticmethod
    def decode_cipher(cipher):
        """Decode signatureCipher"""
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
                url += f"&{sp}={s}"
            
            # Add other parameters
            for key in ['ratebypass', 'mime', 'clen', 'gir', 'dur', 'lmt', 'mt', 'fvip', 'keepalive', 'c', 'txp', 'ei', 'ip', 'id', 'aitags', 'source', 'requiressl', 'mm', 'mn', 'ms', 'mv', 'mvi', 'pl', 'initcwndbps', 'vprv', 'mime', 'gir', 'clen', 'dur', 'lmt', 'txp', 'ei', 'ip', 'id', 'aitags', 'source', 'requiressl', 'mm', 'mn', 'ms', 'mv', 'mvi', 'pl', 'initcwndbps', 'vprv']:
                if key in params:
                    url += f"&{key}={params[key]}"
            
            return url
            
        except:
            return None
    
    @staticmethod
    def get_video_info(video_id):
        """Get comprehensive video information"""
        html = YouTubeMasterParser.get_video_page(video_id)
        if not html:
            return None
        
        data = YouTubeMasterParser.extract_all_data(html)
        
        # Basic info
        info = {
            'video_id': video_id,
            'title': 'Unknown Title',
            'author': 'Unknown Channel',
            'description': '',
            'duration': 0,
            'views': 0,
            'likes': 0,
            'publish_date': '',
            'category': '',
            'keywords': [],
            'thumbnails': {},
            'is_live': False,
            'is_age_restricted': False,
            'allow_ratings': True,
            'is_private': False,
            'is_unlisted': False
        }
        
        # Fill info from video details
        if data['video_details']:
            vd = data['video_details']
            info.update({
                'title': vd.get('title', 'Unknown Title'),
                'author': vd.get('author', 'Unknown Channel'),
                'description': vd.get('shortDescription', ''),
                'duration': int(vd.get('lengthSeconds', 0)),
                'views': int(vd.get('viewCount', 0)),
                'allow_ratings': vd.get('allowRatings', True),
                'is_live': vd.get('isLive', False),
                'is_age_restricted': vd.get('isAgeRestricted', False),
                'is_private': vd.get('isPrivate', False),
                'is_unlisted': vd.get('isUnlisted', False),
                'keywords': vd.get('keywords', [])
            })
        
        # Get additional info from initial data
        if data['initial_data']:
            try:
                # Try to find video primary info
                video_primary_info = YouTubeMasterParser.find_key(data['initial_data'], 'videoPrimaryInfoRenderer')
                if video_primary_info:
                    # Extract likes if available
                    likes_text = YouTubeMasterParser.find_key(video_primary_info, 'simpleText')
                    if likes_text and 'likes' in likes_text.lower():
                        info['likes'] = int(re.sub(r'[^\d]', '', likes_text))
            except:
                pass
        
        # Format duration
        if info['duration'] > 0:
            hours = info['duration'] // 3600
            minutes = (info['duration'] % 3600) // 60
            seconds = info['duration'] % 60
            if hours > 0:
                info['duration_formatted'] = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                info['duration_formatted'] = f"{minutes}:{seconds:02d}"
        else:
            info['duration_formatted'] = "0:00"
        
        # Format views
        if info['views'] >= 1000000000:
            info['views_formatted'] = f"{info['views']/1000000000:.1f}B"
        elif info['views'] >= 1000000:
            info['views_formatted'] = f"{info['views']/1000000:.1f}M"
        elif info['views'] >= 1000:
            info['views_formatted'] = f"{info['views']/1000:.1f}K"
        else:
            info['views_formatted'] = str(info['views'])
        
        # Get thumbnails
        thumbnails = {
            'default': f"https://i.ytimg.com/vi/{video_id}/default.jpg",
            'medium': f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
            'high': f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            'standard': f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
            'maxres': f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
        }
        
        # Update with extracted thumbnails if available
        if data['thumbnails']:
            for thumb in data['thumbnails']:
                width = thumb.get('width', 0)
                url = thumb.get('url', '')
                if width >= 1280:
                    thumbnails['maxres'] = url
                elif width >= 640:
                    thumbnails['standard'] = url
                elif width >= 480:
                    thumbnails['high'] = url
                elif width >= 320:
                    thumbnails['medium'] = url
                else:
                    thumbnails['default'] = url
        
        info['thumbnails'] = thumbnails
        
        return info
    
    @staticmethod
    def find_key(obj, key):
        """Find a key in nested dictionary"""
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for k, v in obj.items():
                result = YouTubeMasterParser.find_key(v, key)
                if result:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = YouTubeMasterParser.find_key(item, key)
                if result:
                    return result
        return None
    
    @staticmethod
    def get_all_formats(video_id):
        """Get all available formats for a video"""
        html = YouTubeMasterParser.get_video_page(video_id)
        if not html:
            return []
        
        data = YouTubeMasterParser.extract_all_data(html)
        formats = YouTubeMasterParser.parse_all_formats(data['streaming_data'])
        
        # Add direct URLs as additional formats
        for url in data['direct_urls']:
            formats.append({
                'itag': 'direct',
                'type': 'video',
                'quality': 'Direct URL',
                'mime_type': 'video/mp4',
                'codec': 'Unknown',
                'url': url,
                'size': 'Unknown',
                'bitrate': 0,
                'fps': 0,
                'width': 0,
                'height': 0,
                'audio_channels': 2,
                'is_progressive': True,
                'has_audio': True,
                'has_video': True
            })
        
        return formats
    
    @staticmethod
    def group_formats_by_quality(formats):
        """Group formats by quality"""
        video_formats = []
        audio_formats = []
        progressive_formats = []
        
        for fmt in formats:
            if fmt['type'] == 'video' and not fmt['has_audio']:
                video_formats.append(fmt)
            elif fmt['type'] == 'audio':
                audio_formats.append(fmt)
            elif fmt['is_progressive']:
                progressive_formats.append(fmt)
        
        return {
            'video_only': sorted(video_formats, key=lambda x: (
                -int(re.search(r'\d+', x['quality']).group()) if re.search(r'\d+', x['quality']) else 0
            )),
            'audio_only': sorted(audio_formats, key=lambda x: (
                -int(re.search(r'\d+', x['quality']).group()) if re.search(r'\d+', x['quality']) else 0
            )),
            'progressive': sorted(progressive_formats, key=lambda x: (
                -int(re.search(r'\d+', x['quality']).group()) if re.search(r'\d+', x['quality']) else 0
            ))
        }

# ==================== API ENDPOINTS ====================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>YouTube Downloader API</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #f5f5f5; color: #333; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { background: #ff0000; color: white; padding: 20px; border-radius: 10px; margin-bottom: 30px; }
        h1 { margin-bottom: 10px; }
        .api-info { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .endpoint { background: #f8f9fa; padding: 15px; margin: 10px 0; border-left: 4px solid #ff0000; border-radius: 5px; }
        .method { display: inline-block; background: #ff0000; color: white; padding: 5px 10px; border-radius: 3px; margin-right: 10px; font-weight: bold; }
        .url { color: #0066cc; font-family: monospace; }
        .form-container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        input[type="text"] { width: 100%; padding: 12px; margin: 10px 0; border: 2px solid #ddd; border-radius: 5px; font-size: 16px; }
        button { background: #ff0000; color: white; border: none; padding: 12px 30px; border-radius: 5px; font-size: 16px; cursor: pointer; margin: 10px 5px; }
        button:hover { background: #cc0000; }
        .response { background: #f8f9fa; padding: 20px; border-radius: 5px; margin-top: 20px; overflow-x: auto; }
        pre { white-space: pre-wrap; word-wrap: break-word; }
        .quality-badge { display: inline-block; background: #28a745; color: white; padding: 3px 8px; border-radius: 3px; margin: 2px; font-size: 12px; }
        .audio-badge { background: #17a2b8; }
        .video-badge { background: #dc3545; }
        .progressive-badge { background: #ffc107; color: #333; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎬 YouTube Downloader API</h1>
            <p>Download YouTube videos in all qualities - No external APIs used</p>
        </header>
        
        <div class="api-info">
            <h2>📚 API Documentation</h2>
            <div class="endpoint">
                <span class="method">GET</span>
                <span class="url">/api/info?url=YOUTUBE_URL</span>
                <p>Get video information (title, author, duration, views, thumbnails)</p>
            </div>
            <div class="endpoint">
                <span class="method">GET</span>
                <span class="url">/api/formats?url=YOUTUBE_URL</span>
                <p>Get all available formats (video, audio, progressive)</p>
            </div>
            <div class="endpoint">
                <span class="method">GET</span>
                <span class="url">/api/download?url=YOUTUBE_URL&itag=ITAG</span>
                <p>Download video in specific format</p>
            </div>
            <div class="endpoint">
                <span class="method">GET</span>
                <span class="url">/api/stream?url=YOUTUBE_URL&itag=ITAG</span>
                <p>Stream video directly</p>
            </div>
            <div class="endpoint">
                <span class="method">GET</span>
                <span class="url">/api/thumbnail?url=YOUTUBE_URL&quality=quality</span>
                <p>Get video thumbnail</p>
            </div>
        </div>
        
        <div class="form-container">
            <h2>🔍 Test the API</h2>
            <form id="testForm">
                <input type="text" id="videoUrl" placeholder="Enter YouTube URL (e.g., https://youtube.com/watch?v=...)" required>
                <div>
                    <button type="button" onclick="getInfo()">Get Video Info</button>
                    <button type="button" onclick="getFormats()">Get All Formats</button>
                    <button type="button" onclick="testDownload()">Test Download</button>
                </div>
            </form>
            <div id="response" class="response" style="display: none;">
                <h3>Response:</h3>
                <pre id="responseText"></pre>
            </div>
        </div>
    </div>
    
    <script>
        function getInfo() {
            const url = document.getElementById('videoUrl').value;
            if (!url) return alert('Please enter a YouTube URL');
            
            fetch(`/api/info?url=${encodeURIComponent(url)}`)
                .then(response => response.json())
                .then(data => {
                    document.getElementById('response').style.display = 'block';
                    document.getElementById('responseText').textContent = JSON.stringify(data, null, 2);
                })
                .catch(error => {
                    document.getElementById('response').style.display = 'block';
                    document.getElementById('responseText').textContent = 'Error: ' + error;
                });
        }
        
        function getFormats() {
            const url = document.getElementById('videoUrl').value;
            if (!url) return alert('Please enter a YouTube URL');
            
            fetch(`/api/formats?url=${encodeURIComponent(url)}`)
                .then(response => response.json())
                .then(data => {
                    document.getElementById('response').style.display = 'block';
                    document.getElementById('responseText').textContent = JSON.stringify(data, null, 2);
                })
                .catch(error => {
                    document.getElementById('response').style.display = 'block';
                    document.getElementById('responseText').textContent = 'Error: ' + error;
                });
        }
        
        function testDownload() {
            const url = document.getElementById('videoUrl').value;
            if (!url) return alert('Please enter a YouTube URL');
            
            // Open download in new tab
            window.open(`/api/download?url=${encodeURIComponent(url)}&itag=18`, '_blank');
        }
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    """Home page with API documentation"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/info', methods=['GET'])
def api_info():
    """Get video information"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeMasterParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    try:
        info = YouTubeMasterParser.get_video_info(video_id)
        if not info:
            return jsonify({"error": "Could not fetch video information"}), 500
        
        # Add API endpoints
        info['endpoints'] = {
            'formats': f"/api/formats?url={quote(url)}",
            'download_sample': f"/api/download?url={quote(url)}&itag=18",
            'thumbnail': f"/api/thumbnail?url={quote(url)}&quality=maxres"
        }
        
        return jsonify({
            "success": True,
            "video_id": video_id,
            "info": info,
            "timestamp": time.time()
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "video_id": video_id
        }), 500

@app.route('/api/formats', methods=['GET'])
def api_formats():
    """Get all available formats"""
    url = request.args.get('url', '')
    group_by = request.args.get('group', 'true').lower() == 'true'
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeMasterParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    try:
        # Get video info
        info = YouTubeMasterParser.get_video_info(video_id)
        
        # Get all formats
        formats = YouTubeMasterParser.get_all_formats(video_id)
        
        if not formats:
            return jsonify({
                "success": False,
                "error": "No formats found. Video might be private, age-restricted, or region blocked.",
                "video_id": video_id
            }), 404
        
        # Group formats if requested
        if group_by:
            grouped = YouTubeMasterParser.group_formats_by_quality(formats)
            
            # Create response with grouped formats
            response = {
                "success": True,
                "video_id": video_id,
                "title": info.get('title', '') if info else 'Unknown',
                "author": info.get('author', '') if info else 'Unknown',
                "formats": {
                    "video_only": [],
                    "audio_only": [],
                    "progressive": []
                },
                "counts": {
                    "total": len(formats),
                    "video_only": len(grouped['video_only']),
                    "audio_only": len(grouped['audio_only']),
                    "progressive": len(grouped['progressive'])
                },
                "timestamp": time.time()
            }
            
            # Add formats with download URLs
            for fmt in grouped['video_only'][:20]:  # Limit to 20 each
                response['formats']['video_only'].append({
                    **fmt,
                    'download_url': f"/api/download?url={quote(url)}&itag={fmt['itag']}",
                    'stream_url': f"/api/stream?url={quote(url)}&itag={fmt['itag']}"
                })
            
            for fmt in grouped['audio_only'][:20]:
                response['formats']['audio_only'].append({
                    **fmt,
                    'download_url': f"/api/download?url={quote(url)}&itag={fmt['itag']}",
                    'stream_url': f"/api/stream?url={quote(url)}&itag={fmt['itag']}"
                })
            
            for fmt in grouped['progressive'][:20]:
                response['formats']['progressive'].append({
                    **fmt,
                    'download_url': f"/api/download?url={quote(url)}&itag={fmt['itag']}",
                    'stream_url': f"/api/stream?url={quote(url)}&itag={fmt['itag']}"
                })
            
            return jsonify(response)
        
        else:
            # Return all formats ungrouped
            formatted_formats = []
            for fmt in formats[:50]:  # Limit to 50
                formatted_formats.append({
                    **fmt,
                    'download_url': f"/api/download?url={quote(url)}&itag={fmt['itag']}",
                    'stream_url': f"/api/stream?url={quote(url)}&itag={fmt['itag']}"
                })
            
            return jsonify({
                "success": True,
                "video_id": video_id,
                "title": info.get('title', '') if info else 'Unknown',
                "count": len(formats),
                "formats": formatted_formats,
                "timestamp": time.time()
            })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "video_id": video_id
        }), 500

@app.route('/api/download', methods=['GET'])
def api_download():
    """Download video in specific format"""
    url = request.args.get('url', '')
    itag = request.args.get('itag', '')
    quality = request.args.get('quality', '')
    filename = request.args.get('filename', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeMasterParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    try:
        # Get all formats
        formats = YouTubeMasterParser.get_all_formats(video_id)
        if not formats:
            return jsonify({"error": "No formats available for this video"}), 404
        
        # Find the requested format
        target_format = None
        
        if itag:
            # Find by itag
            for fmt in formats:
                if str(fmt.get('itag', '')) == str(itag):
                    target_format = fmt
                    break
        
        elif quality:
            # Find by quality
            for fmt in formats:
                if fmt.get('quality', '').lower() == quality.lower():
                    target_format = fmt
                    break
        
        else:
            # Default to first progressive format, or first available
            progressive_formats = [f for f in formats if f.get('is_progressive', False)]
            if progressive_formats:
                target_format = progressive_formats[0]
            elif formats:
                target_format = formats[0]
        
        if not target_format or not target_format.get('url'):
            return jsonify({
                "error": "Format not found",
                "available_formats": [
                    {"itag": f.get('itag'), "quality": f.get('quality'), "type": f.get('type')} 
                    for f in formats[:10]
                ]
            }), 404
        
        download_url = target_format['url']
        
        # Get video info for filename
        info = YouTubeMasterParser.get_video_info(video_id)
        title = info.get('title', f'video_{video_id}') if info else f'video_{video_id}'
        
        # Clean filename
        if not filename:
            filename = re.sub(r'[^\w\-_\. ]', '_', title[:100])
            
            # Add quality and extension
            if target_format['type'] == 'audio':
                filename += f"_{target_format['quality']}.mp3"
                content_type = 'audio/mpeg'
            else:
                filename += f"_{target_format['quality']}.mp4"
                content_type = target_format.get('mime_type', 'video/mp4')
        
        # Stream the download
        headers = {'User-Agent': USER_AGENT}
        
        def generate():
            with requests.get(download_url, headers=headers, stream=True, timeout=TIMEOUT) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=8192):
                    yield chunk
        
        response_headers = {
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': content_type,
            'Cache-Control': 'no-cache'
        }
        
        # Add content length if available
        if target_format.get('size') and 'MB' in target_format['size']:
            # Extract size in bytes for content-length header
            try:
                size_str = target_format['size']
                if 'GB' in size_str:
                    size = float(size_str.replace(' GB', '')) * 1024**3
                elif 'MB' in size_str:
                    size = float(size_str.replace(' MB', '')) * 1024**2
                elif 'KB' in size_str:
                    size = float(size_str.replace(' KB', '')) * 1024
                else:
                    size = float(size_str.replace(' B', ''))
                
                response_headers['Content-Length'] = str(int(size))
            except:
                pass
        
        return Response(
            stream_with_context(generate()),
            headers=response_headers
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/stream', methods=['GET'])
def api_stream():
    """Stream video directly"""
    url = request.args.get('url', '')
    itag = request.args.get('itag', '18')  # Default to 360p
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeMasterParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    try:
        # Get all formats
        formats = YouTubeMasterParser.get_all_formats(video_id)
        if not formats:
            return jsonify({"error": "No formats available for this video"}), 404
        
        # Find the requested format
        target_format = None
        for fmt in formats:
            if str(fmt.get('itag', '')) == str(itag):
                target_format = fmt
                break
        
        # If not found by itag, find a progressive format
        if not target_format:
            for fmt in formats:
                if fmt.get('is_progressive', False):
                    target_format = fmt
                    break
        
        # If still not found, use first format
        if not target_format and formats:
            target_format = formats[0]
        
        if not target_format or not target_format.get('url'):
            return jsonify({"error": "No streamable format found"}), 404
        
        stream_url = target_format['url']
        
        # Stream the video
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(stream_url, headers=headers, stream=True, timeout=TIMEOUT)
        
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                yield chunk
        
        content_type = target_format.get('mime_type', 'video/mp4')
        
        return Response(
            stream_with_context(generate()),
            content_type=content_type,
            headers={
                'Cache-Control': 'no-cache',
                'Accept-Ranges': 'bytes',
                'Content-Disposition': 'inline'
            }
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/thumbnail', methods=['GET'])
def api_thumbnail():
    """Get video thumbnail"""
    url = request.args.get('url', '')
    quality = request.args.get('quality', 'maxres')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeMasterParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Thumbnail qualities
    qualities = {
        'default': 'default.jpg',
        'medium': 'mqdefault.jpg',
        'high': 'hqdefault.jpg',
        'standard': 'sddefault.jpg',
        'maxres': 'maxresdefault.jpg'
    }
    
    thumbnail_file = qualities.get(quality, 'maxresdefault.jpg')
    thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/{thumbnail_file}"
    
    try:
        response = requests.get(thumbnail_url, timeout=TIMEOUT)
        
        if response.status_code == 200:
            return Response(
                response.content,
                content_type='image/jpeg'
            )
        else:
            # Fallback to default
            response = requests.get(f"https://i.ytimg.com/vi/{video_id}/default.jpg", timeout=TIMEOUT)
            return Response(response.content, content_type='image/jpeg')
            
    except:
        return jsonify({"error": "Failed to get thumbnail"}), 500

@app.route('/api/bulk-formats', methods=['GET'])
def api_bulk_formats():
    """Get formats for multiple videos"""
    urls = request.args.getlist('url')
    
    if not urls:
        return jsonify({"error": "At least one URL is required"}), 400
    
    results = []
    for url in urls[:10]:  # Limit to 10 URLs
        try:
            video_id = YouTubeMasterParser.extract_video_id(url)
            if video_id:
                info = YouTubeMasterParser.get_video_info(video_id)
                formats = YouTubeMasterParser.get_all_formats(video_id)
                
                results.append({
                    "url": url,
                    "video_id": video_id,
                    "title": info.get('title', '') if info else 'Unknown',
                    "formats_count": len(formats) if formats else 0,
                    "status": "success"
                })
            else:
                results.append({
                    "url": url,
                    "error": "Invalid YouTube URL",
                    "status": "error"
                })
        except Exception as e:
            results.append({
                "url": url,
                "error": str(e),
                "status": "error"
            })
    
    return jsonify({
        "success": True,
        "count": len(results),
        "results": results,
        "timestamp": time.time()
    })

@app.route('/api/search', methods=['GET'])
def api_search():
    """Search YouTube videos"""
    query = request.args.get('q', '')
    limit = int(request.args.get('limit', 10))
    
    if not query:
        return jsonify({"error": "Search query 'q' is required"}), 400
    
    try:
        search_url = f"https://www.youtube.com/results?search_query={quote(query)}"
        headers = {'User-Agent': USER_AGENT}
        
        response = requests.get(search_url, headers=headers, timeout=TIMEOUT)
        
        if response.status_code != 200:
            return jsonify({"error": "Search failed"}), 500
        
        html = response.text
        
        # Extract video IDs from search results
        video_ids = re.findall(r'watch\?v=([a-zA-Z0-9_-]{11})', html)
        unique_video_ids = []
        seen = set()
        
        for vid in video_ids:
            if vid not in seen:
                seen.add(vid)
                unique_video_ids.append(vid)
                if len(unique_video_ids) >= limit:
                    break
        
        # Get basic info for each video
        videos = []
        for video_id in unique_video_ids[:limit]:
            try:
                info = YouTubeMasterParser.get_video_info(video_id)
                if info:
                    videos.append({
                        "video_id": video_id,
                        "title": info.get('title', ''),
                        "author": info.get('author', ''),
                        "duration": info.get('duration_formatted', ''),
                        "views": info.get('views_formatted', ''),
                        "thumbnail": info.get('thumbnails', {}).get('medium', ''),
                        "url": f"https://youtube.com/watch?v={video_id}"
                    })
            except:
                continue
        
        return jsonify({
            "success": True,
            "query": query,
            "count": len(videos),
            "videos": videos,
            "timestamp": time.time()
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/health', methods=['GET'])
def api_health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "service": "YouTube Downloader API",
        "version": "2.0",
        "uptime": time.time() - app.start_time if hasattr(app, 'start_time') else 0
    })

@app.route('/api/debug/<video_id>', methods=['GET'])
def api_debug(video_id):
    """Debug endpoint for troubleshooting"""
    html = YouTubeMasterParser.get_video_page(video_id)
    
    if not html:
        return jsonify({"error": "Could not fetch video page"}), 500
    
    data = YouTubeMasterParser.extract_all_data(html)
    formats = YouTubeMasterParser.get_all_formats(video_id)
    
    return jsonify({
        "video_id": video_id,
        "html_length": len(html),
        "has_player_response": bool(data['player_response']),
        "has_streaming_data": bool(data['streaming_data']),
        "streaming_data_keys": list(data['streaming_data'].keys()) if data['streaming_data'] else [],
        "formats_count": len(formats),
        "sample_format": formats[0] if formats else None,
        "direct_urls_count": len(data['direct_urls']),
        "sample_direct_url": data['direct_urls'][0] if data['direct_urls'] else None,
        "timestamp": time.time()
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
    print(f"🚀 YouTube Downloader API starting on port {port}")
    print(f"📚 API Documentation: http://localhost:{port}")
    print(f"🔧 Debug endpoint: http://localhost:{port}/api/debug/VIDEO_ID")
    app.run(host='0.0.0.0', port=port, debug=False)
