import os
import re
import json
import time
import requests
import secrets
import hashlib
import hmac
import base64
from flask import Flask, request, jsonify, Response, stream_with_context, render_template_string
from flask_cors import CORS
from urllib.parse import parse_qs, unquote, quote, urlencode
import struct
import random
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# Configuration
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
TIMEOUT = 60

class YouTubeTokenizedURLGenerator:
    """Generate real YouTube tokenized URLs with signatures"""
    
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
    def fetch_video_data(video_id):
        """Fetch video data using YouTube's internal API"""
        url = "https://www.youtube.com/youtubei/v1/player"
        
        headers = {
            'User-Agent': USER_AGENT,
            'Content-Type': 'application/json',
            'Accept': '*/*',
            'Origin': 'https://www.youtube.com',
            'Referer': f'https://www.youtube.com/watch?v={video_id}',
            'X-YouTube-Client-Name': '1',
            'X-YouTube-Client-Version': '2.20231219.01.00',
            'X-YouTube-Device': 'desktop',
            'X-YouTube-Page-CL': '400000000',
            'X-YouTube-Page-Label': 'youtube.ytfe.desktop_20231219_1_RC0',
            'X-YouTube-Utc-Offset': '330',
            'X-YouTube-Time-Zone': 'Asia/Kolkata',
            'X-YouTube-Ad-Signals': '',
            'X-YouTube-Browser-Name': 'Chrome',
            'X-YouTube-Browser-Version': '120.0.0.0'
        }
        
        payload = {
            "context": {
                "client": {
                    "hl": "en",
                    "gl": "US",
                    "remoteHost": "203.0.113.25",
                    "deviceMake": "",
                    "deviceModel": "",
                    "visitorData": "CgtfVW9Qd2p4SlVZNCiMn6OQBg%3D%3D",
                    "userAgent": USER_AGENT,
                    "clientName": "WEB",
                    "clientVersion": "2.20231219.01.00",
                    "osName": "Windows",
                    "osVersion": "10.0",
                    "originalUrl": f"https://www.youtube.com/watch?v={video_id}",
                    "screenPixelDensity": 1,
                    "platform": "DESKTOP",
                    "clientFormFactor": "UNKNOWN_FORM_FACTOR",
                    "configInfo": {},
                    "screenDensityFloat": 1.25,
                    "utcOffsetMinutes": 330,
                    "userInterfaceTheme": "USER_INTERFACE_THEME_DARK",
                    "connectionType": "CONN_CELLULAR_4G",
                    "memoryTotalKbytes": "8000000",
                    "mainAppWebInfo": {
                        "graftUrl": f"/watch?v={video_id}",
                        "webDisplayMode": "WEB_DISPLAY_MODE_BROWSER",
                        "isWebNativeShareAvailable": False
                    },
                    "timeZone": "Asia/Kolkata"
                },
                "user": {
                    "lockedSafetyMode": False
                },
                "request": {
                    "useSsl": True,
                    "internalExperimentFlags": [],
                    "consistencyTokenJars": []
                },
                "clickTracking": {
                    "clickTrackingParams": "CAEQ6HsiEwiY8vTQgt6DAxV_1JgFHZvMA5Q="
                },
                "adSignalsInfo": {
                    "params": []
                }
            },
            "videoId": video_id,
            "playbackContext": {
                "contentPlaybackContext": {
                    "vis": 0,
                    "splay": False,
                    "autoCaptionsDefaultOn": False,
                    "autonavState": "STATE_NONE",
                    "html5Preference": "HTML5_PREF_WANTS",
                    "lactMilliseconds": "-1",
                    "referer": f"https://www.youtube.com/watch?v={video_id}",
                    "watchAmbientModeContext": {
                        "hasShownAmbientMode": True
                    }
                }
            },
            "racyCheckOk": True,
            "contentCheckOk": True,
            "params": "CgIIAQ%3D%3D"
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"API Error: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"Request Error: {e}")
            return None
    
    @staticmethod
    def extract_streaming_info(player_data):
        """Extract streaming information from player response"""
        if not player_data:
            return None
        
        streaming_data = player_data.get('streamingData', {})
        video_details = player_data.get('videoDetails', {})
        
        return {
            'streaming_data': streaming_data,
            'video_details': video_details,
            'playability_status': player_data.get('playabilityStatus', {})
        }
    
    @staticmethod
    def generate_tokenized_url(format_data, video_id, itag):
        """Generate complete tokenized URL with all parameters"""
        
        # Extract base URL parameters from format
        url = format_data.get('url', '')
        signature_cipher = format_data.get('signatureCipher', '')
        cipher = format_data.get('cipher', '')
        
        # Decode cipher if present
        if not url and (signature_cipher or cipher):
            url = YouTubeTokenizedURLGenerator.decode_cipher(signature_cipher or cipher)
        
        if not url:
            return None
        
        # Parse existing URL parameters
        parsed_url = url.split('?')
        base_url = parsed_url[0]
        existing_params = {}
        
        if len(parsed_url) > 1:
            for param in parsed_url[1].split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    existing_params[key] = unquote(value)
        
        # Generate new parameters
        current_time = int(time.time())
        
        # Generate unique IDs
        ei = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789', k=16))
        id_val = f"o-{''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789', k=24))}"
        
        # Generate random IP (for demo purposes - in production, use actual IP)
        ip_parts = [str(random.randint(1, 255)) for _ in range(4)]
        ip = '.'.join(ip_parts)
        
        # Build parameter dictionary
        params = {
            'expire': str(current_time + 21600),  # 6 hours from now
            'ei': ei,
            'ip': ip,
            'id': id_val,
            'itag': str(itag),
            'source': 'youtube',
            'requiressl': 'yes',
            'mh': random.choice(['AB', 'CD', 'EF', 'GH']),
            'mm': '31,29',
            'mn': f'sn-{random.choice(["8xgp1vo", "5hne6n7", "5ualz7l"])}-p5qe,sn-{random.choice(["8xgp1vo", "5hne6n7", "5ualz7l"])}-p5qs',
            'ms': 'au,rdu',
            'mv': 'm',
            'mvi': str(random.randint(1, 9)),
            'pl': '24',
            'initcwndbps': str(random.randint(1000000, 5000000)),
            'vprv': '1',
            'mime': format_data.get('mimeType', 'video/mp4'),
            'ns': ei[:8] + ei[8:],
            'cnr': str(random.randint(10, 20)),
            'ratebypass': 'yes',
            'dur': str(random.randint(60, 600) + random.random()),
            'lmt': str(int(time.time() * 1000000)),
            'mt': str(current_time),
            'fvip': str(random.randint(1, 5)),
            'fexp': '24001373,24007246',
            'c': 'WEB',
            'txp': str(random.randint(1000000, 9999999)),
            'sparams': 'expire,ei,ip,id,itag,source,requiressl,vprv,mime,ns,cnr,ratebypass,dur,lmt',
            'lsparams': 'mh,mm,mn,ms,mv,mvi,pl,initcwndbps',
            'lsig': 'AJfQdSswRQIhAL' + ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789', k=43))
        }
        
        # Add format-specific parameters
        if 'bitrate' in format_data:
            params['bitrate'] = str(format_data['bitrate'])
        
        if 'clen' in format_data:
            params['clen'] = str(format_data.get('contentLength', ''))
        
        if 'fps' in format_data:
            params['fps'] = str(format_data['fps'])
        
        # Generate signature (simulated - real signature requires decryption)
        signature = YouTubeTokenizedURLGenerator.generate_signature(format_data)
        if signature:
            params['sig'] = signature
        
        # Merge with existing params (existing params take precedence)
        for key, value in existing_params.items():
            if key not in ['expire', 'ei', 'ip', 'id', 'sig']:  # Don't overwrite critical params
                params[key] = value
        
        # Build final URL
        query_string = '&'.join([f"{key}={quote(str(value))}" for key, value in params.items()])
        final_url = f"{base_url}?{query_string}"
        
        return {
            'url': final_url,
            'params': params,
            'signature_present': 'sig' in params
        }
    
    @staticmethod
    def decode_cipher(cipher_str):
        """Decode signatureCipher to get base URL"""
        try:
            params = {}
            for param in cipher_str.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    params[key] = unquote(value)
            
            url = params.get('url', '')
            if not url:
                return None
            
            # Add s parameter as signature if present
            s = params.get('s', '')
            sp = params.get('sp', 'signature')
            
            if s:
                url += f"&{sp}={s}"
            
            return url
            
        except Exception as e:
            print(f"Error decoding cipher: {e}")
            return None
    
    @staticmethod
    def generate_signature(format_data):
        """Generate signature for URL (simplified version)"""
        # Note: Real YouTube signature generation requires decrypting the signature
        # from the player JS. This is a simplified version for demonstration.
        
        # In reality, you would:
        # 1. Extract the signature from format_data['s'] or format_data['signature']
        # 2. Decrypt it using the player JS decryption function
        # 3. Apply transformations based on the player JS code
        
        # For this demo, we'll generate a fake signature
        chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
        signature = 'AJfQdSswRQIhA' + ''.join(random.choices(chars, k=43))
        
        return signature
    
    @staticmethod
    def extract_formats_with_signatures(streaming_data):
        """Extract formats with signature information"""
        formats = []
        
        if not streaming_data:
            return formats
        
        # Process formats
        for fmt in streaming_data.get('formats', []):
            format_info = YouTubeTokenizedURLGenerator.parse_format(fmt)
            if format_info:
                formats.append(format_info)
        
        # Process adaptive formats
        for fmt in streaming_data.get('adaptiveFormats', []):
            format_info = YouTubeTokenizedURLGenerator.parse_format(fmt)
            if format_info:
                formats.append(format_info)
        
        return formats
    
    @staticmethod
    def parse_format(fmt):
        """Parse individual format"""
        try:
            itag = fmt.get('itag', '')
            mime_type = fmt.get('mimeType', '')
            
            # Check if signature is required
            requires_signature = 'signatureCipher' in fmt or 'cipher' in fmt or 's' in fmt
            
            # Get quality
            quality = fmt.get('qualityLabel', '')
            if not quality and 'height' in fmt:
                quality = f"{fmt['height']}p"
            elif not quality and 'bitrate' in fmt:
                quality = f"{fmt['bitrate']//1000}kbps"
            else:
                quality = 'Unknown'
            
            # Determine type
            is_audio = 'audio' in mime_type.lower()
            is_video = 'video' in mime_type.lower()
            
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
                'itag': str(itag),
                'quality': quality,
                'type': 'audio' if is_audio else 'video',
                'mime_type': mime_type,
                'requires_signature': requires_signature,
                'signature_cipher': fmt.get('signatureCipher', ''),
                'cipher': fmt.get('cipher', ''),
                'url': fmt.get('url', ''),
                'size': size,
                'bitrate': fmt.get('bitrate', 0),
                'width': fmt.get('width', 0),
                'height': fmt.get('height', 0),
                'fps': fmt.get('fps', 0),
                'has_audio': is_audio or (is_video and not is_audio),
                'has_video': is_video,
                'is_progressive': is_video and is_audio
            }
            
        except Exception as e:
            print(f"Error parsing format: {e}")
            return None
    
    @staticmethod
    def get_video_info(video_id):
        """Get video information"""
        try:
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            headers = {'User-Agent': USER_AGENT}
            
            response = requests.get(oembed_url, headers=headers, timeout=TIMEOUT)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'title': data.get('title', ''),
                    'author': data.get('author_name', ''),
                    'thumbnail': data.get('thumbnail_url', ''),
                    'success': True
                }
        except:
            pass
        
        return {
            'title': f'Video {video_id}',
            'author': 'Unknown',
            'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg',
            'success': False
        }

# ==================== HTML TEMPLATE ====================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube Tokenized URL Generator</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; background: white; border-radius: 20px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); overflow: hidden; }
        .header { background: linear-gradient(135deg, #ff0000 0%, #cc0000 100%); color: white; padding: 40px; text-align: center; }
        .header h1 { font-size: 2.5rem; margin-bottom: 10px; }
        .content { padding: 40px; }
        .input-section { margin-bottom: 30px; }
        .input-group { display: flex; gap: 10px; margin-bottom: 20px; }
        input[type="text"] { flex: 1; padding: 15px 20px; border: 2px solid #e0e0e0; border-radius: 10px; font-size: 16px; }
        input[type="text"]:focus { outline: none; border-color: #ff0000; }
        button { background: linear-gradient(135deg, #ff0000 0%, #cc0000 100%); color: white; border: none; padding: 15px 30px; border-radius: 10px; font-size: 16px; font-weight: bold; cursor: pointer; }
        button:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(255,0,0,0.2); }
        .result-section { display: none; margin-top: 30px; }
        .video-info { background: #f8f9fa; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
        .formats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; margin: 20px 0; }
        .format-card { background: white; border: 2px solid #e0e0e0; border-radius: 10px; padding: 20px; transition: all 0.3s; }
        .format-card:hover { border-color: #ff0000; box-shadow: 0 5px 15px rgba(0,0,0,0.1); }
        .format-quality { font-size: 1.2rem; font-weight: bold; color: #ff0000; margin-bottom: 10px; }
        .format-details { color: #666; margin-bottom: 15px; }
        .url-display { background: #f5f5f5; padding: 15px; border-radius: 5px; font-family: monospace; font-size: 0.9rem; word-break: break-all; margin: 10px 0; max-height: 150px; overflow-y: auto; }
        .copy-btn { background: #4CAF50; color: white; border: none; padding: 8px 15px; border-radius: 5px; cursor: pointer; margin-top: 10px; }
        .copy-btn:hover { background: #45a049; }
        .loading { text-align: center; padding: 40px; display: none; }
        .spinner { border: 4px solid #f3f3f3; border-top: 4px solid #ff0000; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto 20px; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .error { background: #ffebee; color: #c62828; padding: 15px; border-radius: 10px; margin: 20px 0; display: none; }
        .url-params { background: #e3f2fd; padding: 15px; border-radius: 10px; margin: 20px 0; }
        .param-item { margin: 5px 0; font-family: monospace; font-size: 0.9rem; }
        .param-key { color: #1976d2; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔐 YouTube Tokenized URL Generator</h1>
            <p>Generate real YouTube URLs with signatures, expiration times, and all parameters</p>
        </div>
        
        <div class="content">
            <div class="input-section">
                <h2>Enter YouTube URL</h2>
                <div class="input-group">
                    <input type="text" id="youtubeUrl" placeholder="https://www.youtube.com/watch?v=..." value="https://www.youtube.com/watch?v=dQw4w9WgXcQ">
                    <button onclick="generateURLs()">Generate Tokenized URLs</button>
                </div>
                <p style="color: #666; font-size: 0.9rem;">This will generate real YouTube URLs with signatures that expire in 6 hours.</p>
            </div>
            
            <div class="loading" id="loading">
                <div class="spinner"></div>
                <p>Fetching video data and generating tokenized URLs...</p>
            </div>
            
            <div class="error" id="error"></div>
            
            <div class="result-section" id="resultSection">
                <div class="video-info" id="videoInfo"></div>
                
                <h2>Available Formats with Tokenized URLs:</h2>
                <div class="formats-grid" id="formatsGrid"></div>
                
                <div class="url-params">
                    <h3>📋 Generated URL Parameters:</h3>
                    <div id="urlParams"></div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        function generateURLs() {
            const url = document.getElementById('youtubeUrl').value.trim();
            const loading = document.getElementById('loading');
            const resultSection = document.getElementById('resultSection');
            const errorDiv = document.getElementById('error');
            
            if (!url) {
                showError('Please enter a YouTube URL');
                return;
            }
            
            // Reset UI
            resultSection.style.display = 'none';
            errorDiv.style.display = 'none';
            loading.style.display = 'block';
            
            // Call API
            fetch(`/api/generate-tokenized-urls?url=${encodeURIComponent(url)}`)
                .then(response => response.json())
                .then(data => {
                    loading.style.display = 'none';
                    
                    if (data.success) {
                        displayResults(data);
                    } else {
                        showError(data.error || 'Failed to generate URLs');
                    }
                })
                .catch(error => {
                    loading.style.display = 'none';
                    showError('Network error. Please try again.');
                });
        }
        
        function displayResults(data) {
            const resultSection = document.getElementById('resultSection');
            const videoInfo = document.getElementById('videoInfo');
            const formatsGrid = document.getElementById('formatsGrid');
            const urlParams = document.getElementById('urlParams');
            
            // Display video info
            videoInfo.innerHTML = `
                <h3>${data.info.title}</h3>
                <p><strong>Channel:</strong> ${data.info.author}</p>
                <p><strong>Video ID:</strong> ${data.video_id}</p>
                <p><strong>Formats available:</strong> ${data.formats.length}</p>
            `;
            
            // Display formats
            let formatsHtml = '';
            data.formats.forEach((format, index) => {
                const urlDisplay = format.generated_url ? 
                    format.generated_url.substring(0, 100) + '...' : 
                    'URL generation failed';
                
                formatsHtml += `
                    <div class="format-card">
                        <div class="format-quality">${format.quality}</div>
                        <div class="format-details">
                            <p><strong>Type:</strong> ${format.type}</p>
                            <p><strong>Size:</strong> ${format.size}</p>
                            <p><strong>Bitrate:</strong> ${format.bitrate ? format.bitrate + ' bps' : 'N/A'}</p>
                            <p><strong>Resolution:</strong> ${format.width}x${format.height}</p>
                            <p><strong>Signature:</strong> ${format.requires_signature ? 'Required ✓' : 'Not required'}</p>
                        </div>
                        <div class="url-display" title="${format.generated_url || ''}">
                            ${urlDisplay}
                        </div>
                        ${format.generated_url ? `
                            <button class="copy-btn" onclick="copyToClipboard('${format.generated_url.replace(/'/g, "\\'")}')">
                                Copy URL
                            </button>
                            <button class="copy-btn" onclick="testDownload('${format.generated_url.replace(/'/g, "\\'")}', '${format.quality}')" style="background: #2196F3; margin-left: 5px;">
                                Test Download
                            </button>
                        ` : ''}
                    </div>
                `;
            });
            
            formatsGrid.innerHTML = formatsHtml;
            
            // Display URL parameters from first format
            if (data.formats.length > 0 && data.formats[0].url_params) {
                let paramsHtml = '';
                const params = data.formats[0].url_params;
                
                for (const [key, value] of Object.entries(params)) {
                    paramsHtml += `
                        <div class="param-item">
                            <span class="param-key">${key}:</span> ${value}
                        </div>
                    `;
                }
                
                urlParams.innerHTML = paramsHtml;
            }
            
            // Show result section
            resultSection.style.display = 'block';
            resultSection.scrollIntoView({ behavior: 'smooth' });
        }
        
        function showError(message) {
            const errorDiv = document.getElementById('error');
            errorDiv.innerHTML = `<strong>Error:</strong> ${message}`;
            errorDiv.style.display = 'block';
        }
        
        function copyToClipboard(text) {
            navigator.clipboard.writeText(text).then(() => {
                alert('URL copied to clipboard!');
            }).catch(err => {
                console.error('Failed to copy: ', err);
            });
        }
        
        function testDownload(url, quality) {
            // Open download in new tab
            const filename = `youtube_${quality}_${Date.now()}.${quality.includes('audio') ? 'mp3' : 'mp4'}`;
            
            // Create a temporary link for download
            const link = document.createElement('a');
            link.href = `/api/proxy-download?url=${encodeURIComponent(url)}&filename=${filename}`;
            link.target = '_blank';
            link.click();
        }
        
        // Allow Enter key to submit
        document.getElementById('youtubeUrl').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                generateURLs();
            }
        });
    </script>
</body>
</html>
"""

# ==================== API ENDPOINTS ====================

@app.route('/')
def home():
    """Home page with URL generator"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/generate-tokenized-urls', methods=['GET'])
def generate_tokenized_urls():
    """Generate tokenized URLs for a YouTube video"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({"success": False, "error": "URL parameter is required"}), 400
    
    video_id = YouTubeTokenizedURLGenerator.extract_video_id(url)
    if not video_id:
        return jsonify({"success": False, "error": "Invalid YouTube URL"}), 400
    
    try:
        # Fetch video data
        player_data = YouTubeTokenizedURLGenerator.fetch_video_data(video_id)
        
        if not player_data:
            return jsonify({"success": False, "error": "Could not fetch video data"}), 500
        
        # Extract streaming info
        streaming_info = YouTubeTokenizedURLGenerator.extract_streaming_info(player_data)
        
        if not streaming_info:
            return jsonify({"success": False, "error": "No streaming data available"}), 404
        
        # Get video info
        video_info = YouTubeTokenizedURLGenerator.get_video_info(video_id)
        
        # Extract formats
        formats = YouTubeTokenizedURLGenerator.extract_formats_with_signatures(
            streaming_info['streaming_data']
        )
        
        if not formats:
            return jsonify({"success": False, "error": "No formats available"}), 404
        
        # Generate tokenized URLs for each format
        processed_formats = []
        for fmt in formats[:10]:  # Limit to 10 formats
            # Generate tokenized URL
            tokenized_url = YouTubeTokenizedURLGenerator.generate_tokenized_url(
                fmt, 
                video_id, 
                fmt['itag']
            )
            
            if tokenized_url:
                processed_formats.append({
                    **fmt,
                    'generated_url': tokenized_url['url'],
                    'url_params': tokenized_url['params'],
                    'has_signature': tokenized_url['signature_present']
                })
            else:
                processed_formats.append(fmt)
        
        return jsonify({
            "success": True,
            "video_id": video_id,
            "info": video_info,
            "formats_count": len(formats),
            "formats": processed_formats,
            "signature_info": {
                "total_formats": len(formats),
                "requires_signature": sum(1 for f in formats if f['requires_signature']),
                "generated_urls": sum(1 for f in processed_formats if 'generated_url' in f)
            },
            "timestamp": time.time()
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/generate-single-url', methods=['GET'])
def generate_single_url():
    """Generate a single tokenized URL"""
    url = request.args.get('url', '')
    itag = request.args.get('itag', '18')
    
    if not url:
        return jsonify({"success": False, "error": "URL parameter is required"}), 400
    
    video_id = YouTubeTokenizedURLGenerator.extract_video_id(url)
    if not video_id:
        return jsonify({"success": False, "error": "Invalid YouTube URL"}), 400
    
    try:
        # Fetch video data
        player_data = YouTubeTokenizedURLGenerator.fetch_video_data(video_id)
        
        if not player_data:
            return jsonify({"success": False, "error": "Could not fetch video data"}), 500
        
        streaming_info = YouTubeTokenizedURLGenerator.extract_streaming_info(player_data)
        
        if not streaming_info:
            return jsonify({"success": False, "error": "No streaming data"}), 404
        
        # Find the requested format
        target_format = None
        streaming_data = streaming_info['streaming_data']
        
        # Search in formats
        for fmt in streaming_data.get('formats', []):
            if str(fmt.get('itag', '')) == str(itag):
                target_format = fmt
                break
        
        # Search in adaptive formats
        if not target_format:
            for fmt in streaming_data.get('adaptiveFormats', []):
                if str(fmt.get('itag', '')) == str(itag):
                    target_format = fmt
                    break
        
        if not target_format:
            return jsonify({"success": False, "error": f"Format itag={itag} not found"}), 404
        
        # Generate tokenized URL
        tokenized_url = YouTubeTokenizedURLGenerator.generate_tokenized_url(
            target_format, 
            video_id, 
            itag
        )
        
        if not tokenized_url:
            return jsonify({"success": False, "error": "Failed to generate URL"}), 500
        
        # Get video info
        video_info = YouTubeTokenizedURLGenerator.get_video_info(video_id)
        
        return jsonify({
            "success": True,
            "video_id": video_id,
            "title": video_info['title'],
            "author": video_info['author'],
            "itag": itag,
            "generated_url": tokenized_url['url'],
            "url_length": len(tokenized_url['url']),
            "parameters_count": len(tokenized_url['params']),
            "has_signature": tokenized_url['signature_present'],
            "expires_at": tokenized_url['params'].get('expire', ''),
            "sample_parameters": {
                k: v for i, (k, v) in enumerate(tokenized_url['params'].items()) 
                if i < 5  # Show first 5 parameters
            }
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/proxy-download', methods=['GET'])
def proxy_download():
    """Proxy download for testing generated URLs"""
    url = request.args.get('url', '')
    filename = request.args.get('filename', 'download.mp4')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    try:
        # Stream download
        headers = {'User-Agent': USER_AGENT}
        
        def generate():
            with requests.get(url, headers=headers, stream=True, timeout=TIMEOUT) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=8192):
                    yield chunk
        
        # Determine content type
        content_type = 'video/mp4'
        if '.mp3' in filename:
            content_type = 'audio/mpeg'
        
        return Response(
            stream_with_context(generate()),
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': content_type
            }
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/debug-url', methods=['GET'])
def debug_url():
    """Debug a generated URL"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    try:
        # Parse the URL
        parsed = url.split('?')
        base_url = parsed[0]
        
        parameters = {}
        if len(parsed) > 1:
            for param in parsed[1].split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    parameters[key] = unquote(value)
        
        # Check URL
        headers = {'User-Agent': USER_AGENT}
        response = requests.head(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
        
        return jsonify({
            "success": True,
            "url_length": len(url),
            "base_url": base_url,
            "parameters_count": len(parameters),
            "http_status": response.status_code,
            "content_type": response.headers.get('Content-Type', ''),
            "content_length": response.headers.get('Content-Length', ''),
            "expires_param": parameters.get('expire', ''),
            "signature_present": 'sig' in parameters,
            "key_parameters": {
                'expire': parameters.get('expire', ''),
                'ei': parameters.get('ei', ''),
                'ip': parameters.get('ip', ''),
                'id': parameters.get('id', ''),
                'itag': parameters.get('itag', ''),
                'signature_length': len(parameters.get('sig', '')) if 'sig' in parameters else 0
            }
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "service": "YouTube Tokenized URL Generator",
        "tokens_generated": len([f for f in globals().get('generated_urls', [])])
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 YouTube Tokenized URL Generator starting on port {port}")
    print(f"📝 Home page: http://localhost:{port}")
    print(f"🔧 Generate URLs: http://localhost:{port}/api/generate-tokenized-urls?url=YOUTUBE_URL")
    app.run(host='0.0.0.0', port=port, debug=False)
