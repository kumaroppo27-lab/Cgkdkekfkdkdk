from flask import Flask, request, jsonify, Response, stream_with_context
import requests
import re
import json
import time
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)

# User-Agent header (YouTube को लगेगा कि browser से request आ रही है)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

@app.route('/')
def home():
    return '''
    <html>
    <head><title>YouTube Downloader API</title></head>
    <body>
        <h1>YouTube Downloader API</h1>
        <p>Endpoints:</p>
        <ul>
            <li><code>/info?url=YOUTUBE_URL</code> - Get video info</li>
            <li><code>/download?url=YOUTUBE_URL</code> - Get download links</li>
            <li><code>/direct?url=YOUTUBE_URL&quality=360</code> - Direct download</li>
        </ul>
        
        <h3>Test Form:</h3>
        <form action="/info" method="get">
            <input type="text" name="url" placeholder="YouTube URL" size="50">
            <button type="submit">Get Info</button>
        </form>
    </body>
    </html>
    '''

@app.route('/extract', methods=['GET'])
def extract_info():
    """Extract video info from YouTube"""
    url = request.args.get('url')
    
    if not url:
        return jsonify({"error": "URL required"}), 400
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    try:
        # Method 1: Try to get from YouTube page directly
        info = get_video_info_direct(video_id)
        
        if info:
            # Add download formats
            info['formats'] = generate_download_links(video_id)
            return jsonify(info)
        else:
            return jsonify({"error": "Could not fetch video info"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def extract_video_id(url):
    """Extract video ID from YouTube URL"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=)([a-zA-Z0-9_-]{11})',
        r'(?:youtu\.be\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    # If URL is directly the video ID
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return url
    
    return None

def get_video_info_direct(video_id):
    """Get video info by scraping YouTube page"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        
        if response.status_code != 200:
            return None
        
        html = response.text
        
        # Extract title (multiple methods)
        title = None
        
        # Method 1: From meta tag
        title_match = re.search(r'<meta name="title" content="([^"]+)"', html)
        if title_match:
            title = title_match.group(1)
        
        # Method 2: From JSON-LD
        if not title:
            jsonld_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
            if jsonld_match:
                try:
                    data = json.loads(jsonld_match.group(1))
                    if isinstance(data, dict):
                        title = data.get('name', '')
                    elif isinstance(data, list) and len(data) > 0:
                        title = data[0].get('name', '')
                except:
                    pass
        
        # Method 3: From inline JSON
        if not title:
            yt_initial_match = re.search(r'var ytInitialData = ({.*?});', html, re.DOTALL)
            if yt_initial_match:
                try:
                    data = json.loads(yt_initial_match.group(1))
                    # Navigate through the complex JSON structure
                    video_details = find_in_dict(data, 'videoDetails')
                    if video_details:
                        title = video_details.get('title', '')
                except:
                    pass
        
        # Extract channel name
        channel_name = "Unknown Channel"
        channel_match = re.search(r'"author":"([^"]+)"', html)
        if channel_match:
            channel_name = channel_match.group(1)
        
        # Get video duration
        duration = "Unknown"
        duration_match = re.search(r'"approxDurationMs":"(\d+)"', html)
        if duration_match:
            seconds = int(duration_match.group(1)) // 1000
            minutes, seconds = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            if hours > 0:
                duration = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                duration = f"{minutes}:{seconds:02d}"
        
        # Get view count
        views = "Unknown"
        views_match = re.search(r'"viewCount":"(\d+)"', html)
        if views_match:
            views = format(int(views_match.group(1)), ',')
        
        # Thumbnails
        thumbnails = {
            "default": f"https://img.youtube.com/vi/{video_id}/default.jpg",
            "medium": f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
            "high": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
            "standard": f"https://img.youtube.com/vi/{video_id}/sddefault.jpg",
            "maxres": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
        }
        
        return {
            "video_id": video_id,
            "title": title or "Unknown Title",
            "channel": channel_name,
            "duration": duration,
            "views": views,
            "thumbnails": thumbnails,
            "url": url,
            "timestamp": time.time()
        }
        
    except Exception as e:
        print(f"Error fetching info: {e}")
        return None

def find_in_dict(data, target_key):
    """Recursively find a key in nested dictionary"""
    if isinstance(data, dict):
        if target_key in data:
            return data[target_key]
        for key, value in data.items():
            result = find_in_dict(value, target_key)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = find_in_dict(item, target_key)
            if result:
                return result
    return None

def generate_download_links(video_id):
    """Generate download links for different qualities"""
    # Note: Actual streaming URLs would require proper extraction
    # This is a template for the response structure
    
    formats = []
    
    # Video formats
    video_formats = [
        {"quality": "144p", "label": "144p (Lowest)", "size": "~2-5 MB"},
        {"quality": "360p", "label": "360p (Medium)", "size": "~5-15 MB"},
        {"quality": "720p", "label": "720p (HD)", "size": "~20-50 MB"},
        {"quality": "1080p", "label": "1080p (Full HD)", "size": "~50-150 MB"},
    ]
    
    for fmt in video_formats:
        formats.append({
            "url": f"/stream/{video_id}?quality={fmt['quality']}",
            "quality": fmt["quality"],
            "label": fmt["label"],
            "type": "video/mp4",
            "size": fmt["size"],
            "download_url": f"https://your-api.onrender.com/direct/{video_id}?quality={fmt['quality']}"
        })
    
    # Audio format
    formats.append({
        "url": f"/stream/{video_id}?quality=audio",
        "quality": "audio",
        "label": "Audio Only (MP3)",
        "type": "audio/mpeg",
        "size": "~3-10 MB",
        "download_url": f"https://your-api.onrender.com/direct/{video_id}?quality=audio"
    })
    
    return formats

@app.route('/stream/<video_id>', methods=['GET'])
def stream_video(video_id):
    """Stream video through proxy"""
    quality = request.args.get('quality', '360p')
    
    # This is a simplified example
    # In production, you would:
    # 1. Get the actual streaming URL from YouTube
    # 2. Stream it to the client
    
    try:
        # Example streaming logic (pseudo-code)
        if quality == 'audio':
            # For audio streaming
            stream_url = get_audio_stream_url(video_id)
        else:
            # For video streaming
            stream_url = get_video_stream_url(video_id, quality)
        
        if not stream_url:
            return jsonify({"error": "Stream not available"}), 404
        
        # Proxy the stream (simplified)
        def generate():
            # In reality, you would stream chunks from YouTube
            yield f"Streaming video {video_id} at {quality}p\n".encode()
            yield "This is a placeholder. Actual implementation required.\n".encode()
        
        return Response(generate(), mimetype='text/plain')
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/direct/<video_id>', methods=['GET'])
def direct_download(video_id):
    """Initiate direct download"""
    quality = request.args.get('quality', '360p')
    
    # In production, this would:
    # 1. Fetch the actual video URL from YouTube
    # 2. Stream it to the user as a download
    
    return jsonify({
        "message": "Direct download endpoint",
        "video_id": video_id,
        "quality": quality,
        "note": "This requires proper implementation with actual video URL fetching",
        "example": {
            "actual_implementation": "Would fetch from https://rr2---sn-xxxx.googlevideo.com/...",
            "current_status": "Placeholder endpoint"
        }
    })

# Helper functions for actual implementation
def get_video_stream_url(video_id, quality):
    """Get actual video stream URL from YouTube"""
    # This is where you would implement actual URL extraction
    # Methods:
    # 1. Use yt-dlp library
    # 2. Parse YouTube player response
    # 3. Use invidious/innertube APIs
    
    # Placeholder
    return None

def get_audio_stream_url(video_id):
    """Get audio stream URL from YouTube"""
    # Similar to above but for audio only
    return None

@app.route('/test')
def test_endpoint():
    """Test endpoint with a known video"""
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    video_id = extract_video_id(test_url)
    
    info = get_video_info_direct(video_id)
    if info:
        info['formats'] = generate_download_links(video_id)
        return jsonify(info)
    
    return jsonify({"error": "Test failed"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
