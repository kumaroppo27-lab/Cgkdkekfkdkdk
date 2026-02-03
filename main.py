import os
import re
import json
import time
import requests
import secrets
import hashlib
from flask import Flask, request, jsonify, Response, stream_with_context, render_template_string, send_file
from flask_cors import CORS
from urllib.parse import parse_qs, unquote, quote, urlencode
import yt_dlp
import tempfile
import threading
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# Configuration
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
TIMEOUT = 60

class YouTubeRealDownloader:
    """Real YouTube downloader that generates actual googlevideo URLs"""
    
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
    def get_real_stream_url(video_id, format_id='best'):
        """Get real streaming URL using yt-dlp"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': format_id,
                'extract_flat': False,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
                
                if info and 'url' in info:
                    # This is the actual googlevideo.com URL
                    return {
                        'url': info['url'],
                        'direct_url': info['url'],
                        'format_id': format_id,
                        'ext': info.get('ext', 'mp4'),
                        'filesize': info.get('filesize', 0),
                        'has_drm': False
                    }
                
                # If direct URL not found, try to get from formats
                if 'formats' in info:
                    for fmt in info['formats']:
                        if fmt.get('format_id') == format_id and 'url' in fmt:
                            return {
                                'url': fmt['url'],
                                'direct_url': fmt['url'],
                                'format_id': format_id,
                                'ext': fmt.get('ext', 'mp4'),
                                'filesize': fmt.get('filesize', 0),
                                'has_drm': fmt.get('has_drm', False)
                            }
            
            return None
            
        except Exception as e:
            print(f"Error getting stream URL: {e}")
            return None
    
    @staticmethod
    def get_video_info(video_id):
        """Get comprehensive video information"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
                
                if not info:
                    return None
                
                # Get all available formats
                formats = []
                if 'formats' in info:
                    for fmt in info['formats']:
                        if fmt.get('url'):
                            format_info = YouTubeRealDownloader.parse_format(fmt)
                            if format_info:
                                formats.append(format_info)
                
                # Sort formats by quality
                formats.sort(key=lambda x: (
                    0 if x['type'] == 'video+audio' else (1 if x['type'] == 'video' else 2),
                    -x.get('height', 0),
                    -x.get('tbr', 0)
                ))
                
                return {
                    'video_id': video_id,
                    'title': info.get('title', ''),
                    'channel': info.get('channel', ''),
                    'duration': info.get('duration_string', ''),
                    'views': info.get('view_count', 0),
                    'description': info.get('description', '')[:200] + '...' if info.get('description') else '',
                    'thumbnail': info.get('thumbnail', f'https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg'),
                    'formats': formats,
                    'format_count': len(formats)
                }
                
        except Exception as e:
            print(f"Error getting video info: {e}")
            return None
    
    @staticmethod
    def parse_format(fmt):
        """Parse format information"""
        format_id = fmt.get('format_id', '')
        format_note = fmt.get('format_note', '')
        ext = fmt.get('ext', '')
        filesize = fmt.get('filesize', fmt.get('filesize_approx', 0))
        url = fmt.get('url', '')
        
        # Determine quality
        if format_note:
            quality = format_note
        elif fmt.get('height'):
            quality = f"{fmt['height']}p"
        elif fmt.get('tbr'):
            quality = f"{fmt['tbr']}kbps"
        else:
            quality = 'Unknown'
        
        # Determine type
        has_video = fmt.get('vcodec') != 'none'
        has_audio = fmt.get('acodec') != 'none'
        
        if has_video and has_audio:
            format_type = 'video+audio'
        elif has_video:
            format_type = 'video'
        else:
            format_type = 'audio'
        
        # Format size
        if filesize:
            if filesize >= 1024**3:
                size = f"{filesize/(1024**3):.1f} GB"
            elif filesize >= 1024**2:
                size = f"{filesize/(1024**2):.1f} MB"
            elif filesize >= 1024:
                size = f"{filesize/1024:.1f} KB"
            else:
                size = f"{filesize} B"
        else:
            size = "Unknown"
        
        # Check if it's a real googlevideo URL
        is_googlevideo = 'googlevideo.com' in url if url else False
        
        return {
            'format_id': format_id,
            'quality': quality,
            'type': format_type,
            'extension': ext,
            'size': size,
            'has_video': has_video,
            'has_audio': has_audio,
            'fps': fmt.get('fps', 0),
            'width': fmt.get('width', 0),
            'height': fmt.get('height', 0),
            'tbr': fmt.get('tbr', 0),
            'vcodec': fmt.get('vcodec', ''),
            'acodec': fmt.get('acodec', ''),
            'url': url,
            'is_googlevideo': is_googlevideo,
            'has_drm': fmt.get('has_drm', False)
        }
    
    @staticmethod
    def generate_download_token(video_id, format_id, quality):
        """Generate a download token for tracking"""
        token = secrets.token_urlsafe(32)
        timestamp = int(time.time())
        
        return {
            'token': token,
            'video_id': video_id,
            'format_id': format_id,
            'quality': quality,
            'created_at': timestamp,
            'expires_at': timestamp + 3600,  # 1 hour
            'status': 'pending'
        }
    
    @staticmethod
    def stream_video_directly(video_id, format_id):
        """Stream video directly from googlevideo"""
        stream_info = YouTubeRealDownloader.get_real_stream_url(video_id, format_id)
        
        if not stream_info or not stream_info.get('url'):
            return None
        
        try:
            # Stream with proper headers
            headers = {
                'User-Agent': USER_AGENT,
                'Accept': '*/*',
                'Accept-Encoding': 'identity',
                'Range': 'bytes=0-',
                'Referer': 'https://www.youtube.com/',
                'Origin': 'https://www.youtube.com'
            }
            
            response = requests.get(stream_info['url'], headers=headers, stream=True, timeout=TIMEOUT)
            
            def generate():
                for chunk in response.iter_content(chunk_size=8192):
                    yield chunk
            
            # Determine content type
            content_type = 'video/mp4'
            if stream_info['ext'] == 'webm':
                content_type = 'video/webm'
            elif 'audio' in format_id:
                content_type = 'audio/mpeg'
            
            return Response(
                stream_with_context(generate()),
                content_type=content_type,
                headers={
                    'Accept-Ranges': 'bytes',
                    'Content-Type': content_type,
                    'Cache-Control': 'no-cache',
                    'Content-Disposition': 'inline'
                }
            )
            
        except Exception as e:
            print(f"Stream error: {e}")
            return None

# Store active downloads
active_downloads = {}

# ==================== HTML TEMPLATE ====================

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎬 YouTube Video Downloader</title>
    <style>
        :root {
            --primary: #FF0000;
            --primary-dark: #CC0000;
            --secondary: #282828;
            --light: #FFFFFF;
            --dark: #0F0F0F;
            --gray: #AAAAAA;
            --success: #28A745;
            --card-bg: #1A1A1A;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Roboto', 'Segoe UI', Arial, sans-serif;
            background: var(--dark);
            color: var(--light);
            min-height: 100vh;
            line-height: 1.6;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            text-align: center;
            padding: 40px 20px;
            background: linear-gradient(135deg, var(--dark), #1A1A1A);
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            margin-bottom: 30px;
        }
        
        .logo {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .logo-icon {
            font-size: 3rem;
            color: var(--primary);
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.1); }
            100% { transform: scale(1); }
        }
        
        h1 {
            font-size: 2.8rem;
            font-weight: 700;
            background: linear-gradient(45deg, var(--primary), #FF6B6B);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 10px;
        }
        
        .subtitle {
            color: var(--gray);
            font-size: 1.1rem;
            max-width: 600px;
            margin: 0 auto;
        }
        
        .main-card {
            background: var(--card-bg);
            border-radius: 20px;
            padding: 40px;
            margin-bottom: 30px;
            border: 1px solid rgba(255, 255, 255, 0.05);
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
        }
        
        .input-section {
            margin-bottom: 30px;
        }
        
        .input-group {
            display: flex;
            gap: 15px;
            margin-bottom: 20px;
        }
        
        input[type="text"] {
            flex: 1;
            padding: 18px 25px;
            background: rgba(255, 255, 255, 0.05);
            border: 2px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            font-size: 16px;
            color: var(--light);
            transition: all 0.3s;
            font-family: inherit;
        }
        
        input[type="text"]:focus {
            outline: none;
            border-color: var(--primary);
            background: rgba(255, 255, 255, 0.08);
            box-shadow: 0 0 0 3px rgba(255, 0, 0, 0.1);
        }
        
        input[type="text"]::placeholder {
            color: rgba(255, 255, 255, 0.4);
        }
        
        .btn {
            padding: 18px 35px;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            font-family: inherit;
            text-decoration: none;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, var(--primary), var(--primary-dark));
            color: white;
        }
        
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(255, 0, 0, 0.3);
        }
        
        .btn-success {
            background: linear-gradient(135deg, var(--success), #1E7E34);
            color: white;
        }
        
        .btn-success:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(40, 167, 69, 0.3);
        }
        
        .btn-secondary {
            background: rgba(255, 255, 255, 0.08);
            color: white;
            border: 1px solid rgba(255, 255, 255, 0.15);
        }
        
        .btn-secondary:hover {
            background: rgba(255, 255, 255, 0.15);
        }
        
        .utility-buttons {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 10px;
        }
        
        .loading {
            text-align: center;
            padding: 50px 20px;
            display: none;
        }
        
        .spinner {
            width: 60px;
            height: 60px;
            border: 4px solid rgba(255, 255, 255, 0.1);
            border-top: 4px solid var(--primary);
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .error {
            background: rgba(220, 53, 69, 0.15);
            border: 1px solid rgba(220, 53, 69, 0.3);
            color: #FF6B6B;
            padding: 18px;
            border-radius: 10px;
            margin: 20px 0;
            display: none;
        }
        
        .result-section {
            display: none;
        }
        
        .video-info {
            display: grid;
            grid-template-columns: 300px 1fr;
            gap: 30px;
            margin-bottom: 40px;
            background: rgba(0, 0, 0, 0.2);
            padding: 25px;
            border-radius: 15px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }
        
        @media (max-width: 768px) {
            .video-info {
                grid-template-columns: 1fr;
            }
        }
        
        .thumbnail-container {
            position: relative;
        }
        
        .video-thumbnail {
            width: 100%;
            border-radius: 12px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
        }
        
        .duration-badge {
            position: absolute;
            bottom: 15px;
            right: 15px;
            background: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 0.9rem;
            font-weight: 500;
        }
        
        .video-details {
            padding: 10px 0;
        }
        
        .video-title {
            font-size: 1.8rem;
            font-weight: 600;
            margin-bottom: 15px;
            line-height: 1.3;
        }
        
        .video-meta {
            color: var(--gray);
            margin-bottom: 20px;
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
        }
        
        .video-meta span {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .video-description {
            color: rgba(255, 255, 255, 0.7);
            line-height: 1.6;
            margin-top: 20px;
            font-size: 0.95rem;
        }
        
        .quality-section {
            margin: 40px 0;
        }
        
        .section-title {
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 25px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .quality-filters {
            display: flex;
            gap: 10px;
            margin-bottom: 25px;
            flex-wrap: wrap;
        }
        
        .filter-btn {
            padding: 12px 25px;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            color: var(--gray);
            cursor: pointer;
            transition: all 0.3s;
            font-size: 0.95rem;
        }
        
        .filter-btn:hover {
            background: rgba(255, 255, 255, 0.1);
            color: white;
        }
        
        .filter-btn.active {
            background: rgba(255, 0, 0, 0.2);
            border-color: var(--primary);
            color: white;
        }
        
        .formats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 20px;
        }
        
        .format-card {
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 15px;
            padding: 25px;
            transition: all 0.3s;
            cursor: pointer;
            position: relative;
        }
        
        .format-card:hover {
            transform: translateY(-5px);
            border-color: var(--primary);
            box-shadow: 0 15px 35px rgba(255, 0, 0, 0.15);
        }
        
        .format-card.selected {
            border-color: var(--primary);
            background: rgba(255, 0, 0, 0.1);
        }
        
        .format-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        
        .format-quality {
            font-size: 1.4rem;
            font-weight: 600;
            color: white;
        }
        
        .format-badge {
            padding: 5px 12px;
            background: rgba(255, 0, 0, 0.2);
            color: var(--primary);
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
        }
        
        .format-details {
            margin-bottom: 20px;
        }
        
        .detail-row {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
            font-size: 0.9rem;
        }
        
        .detail-label {
            color: var(--gray);
        }
        
        .detail-value {
            color: white;
            font-weight: 500;
        }
        
        .format-size {
            color: var(--success);
            font-weight: 600;
        }
        
        .format-codecs {
            display: flex;
            gap: 10px;
            margin-top: 15px;
        }
        
        .codec-badge {
            padding: 4px 10px;
            background: rgba(255, 255, 255, 0.08);
            border-radius: 6px;
            font-size: 0.8rem;
            color: rgba(255, 255, 255, 0.7);
        }
        
        .download-section {
            margin-top: 40px;
            padding-top: 30px;
            border-top: 1px solid rgba(255, 255, 255, 0.08);
        }
        
        .download-options {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        
        .download-option {
            background: rgba(0, 0, 0, 0.2);
            border-radius: 15px;
            padding: 25px;
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.08);
            transition: all 0.3s;
        }
        
        .download-option:hover {
            border-color: var(--primary);
            transform: translateY(-3px);
        }
        
        .option-icon {
            font-size: 2.5rem;
            margin-bottom: 15px;
            color: var(--primary);
        }
        
        .option-title {
            font-size: 1.2rem;
            font-weight: 600;
            margin-bottom: 10px;
        }
        
        .option-desc {
            color: var(--gray);
            font-size: 0.9rem;
            margin-bottom: 20px;
            line-height: 1.5;
        }
        
        .progress-container {
            margin-top: 30px;
            display: none;
        }
        
        .progress-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
        }
        
        .progress-bar {
            width: 100%;
            height: 10px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 5px;
            overflow: hidden;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--primary), #FF6B6B);
            border-radius: 5px;
            width: 0%;
            transition: width 0.3s;
        }
        
        .progress-stats {
            display: flex;
            justify-content: space-between;
            margin-top: 10px;
            color: var(--gray);
            font-size: 0.9rem;
        }
        
        .url-display {
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 15px;
            margin-top: 20px;
            font-family: monospace;
            font-size: 0.85rem;
            color: rgba(255, 255, 255, 0.7);
            word-break: break-all;
            max-height: 150px;
            overflow-y: auto;
            display: none;
        }
        
        .features {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 25px;
            margin-top: 60px;
        }
        
        .feature-card {
            background: rgba(255, 255, 255, 0.03);
            padding: 30px;
            border-radius: 15px;
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.05);
            transition: all 0.3s;
        }
        
        .feature-card:hover {
            border-color: var(--primary);
            transform: translateY(-5px);
        }
        
        .feature-icon {
            font-size: 2.8rem;
            margin-bottom: 20px;
            color: var(--primary);
        }
        
        .feature-title {
            font-size: 1.3rem;
            font-weight: 600;
            margin-bottom: 15px;
        }
        
        .feature-desc {
            color: var(--gray);
            line-height: 1.6;
        }
        
        footer {
            text-align: center;
            margin-top: 80px;
            padding-top: 30px;
            border-top: 1px solid rgba(255, 255, 255, 0.08);
            color: var(--gray);
            font-size: 0.9rem;
        }
        
        .footer-links {
            display: flex;
            justify-content: center;
            gap: 30px;
            margin-top: 20px;
        }
        
        .footer-links a {
            color: var(--gray);
            text-decoration: none;
            transition: color 0.3s;
        }
        
        .footer-links a:hover {
            color: var(--primary);
        }
        
        @media (max-width: 768px) {
            .container {
                padding: 15px;
            }
            
            .main-card {
                padding: 25px;
            }
            
            h1 {
                font-size: 2.2rem;
            }
            
            .input-group {
                flex-direction: column;
            }
            
            .formats-grid {
                grid-template-columns: 1fr;
            }
            
            .download-options {
                grid-template-columns: 1fr;
            }
            
            .features {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">
                <div class="logo-icon">▶️</div>
            </div>
            <h1>YouTube Video Downloader</h1>
            <p class="subtitle">Download any YouTube video in HD quality. Fast, free, and works with all videos including shorts and live streams.</p>
        </header>
        
        <div class="main-card">
            <div class="input-section">
                <h2 style="margin-bottom: 20px; font-size: 1.4rem; color: white;">Paste YouTube Link</h2>
                <div class="input-group">
                    <input type="text" id="youtubeUrl" 
                           placeholder="https://www.youtube.com/watch?v=... or https://youtu.be/..."
                           autocomplete="off"
                           value="">
                    <button class="btn btn-primary" onclick="getVideoInfo()" id="analyzeBtn">
                        <span>🔍 Analyze Video</span>
                    </button>
                </div>
                
                <div class="utility-buttons">
                    <button class="btn btn-secondary" onclick="pasteFromClipboard()">
                        📋 Paste from Clipboard
                    </button>
                    <button class="btn btn-secondary" onclick="clearInput()">
                        🗑️ Clear
                    </button>
                    <button class="btn btn-secondary" onclick="showExample()">
                        📝 Show Example
                    </button>
                </div>
            </div>
            
            <div class="loading" id="loading">
                <div class="spinner"></div>
                <p style="color: #aaa; margin-top: 20px; font-size: 1.1rem;">Fetching video information...</p>
                <p style="color: #666; margin-top: 10px; font-size: 0.9rem;">This may take a few seconds</p>
            </div>
            
            <div class="error" id="error"></div>
            
            <div class="result-section" id="resultSection">
                <div class="video-info" id="videoInfo">
                    <!-- Video info will be inserted here -->
                </div>
                
                <div class="quality-section">
                    <div class="section-title">
                        <span>🎯 Select Quality</span>
                    </div>
                    
                    <div class="quality-filters">
                        <button class="filter-btn active" onclick="filterFormats('all')">All Formats</button>
                        <button class="filter-btn" onclick="filterFormats('video+audio')">Video + Audio</button>
                        <button class="filter-btn" onclick="filterFormats('video')">Video Only</button>
                        <button class="filter-btn" onclick="filterFormats('audio')">Audio Only</button>
                        <button class="filter-btn" onclick="filterFormats('hd')">HD (720p+)</button>
                    </div>
                    
                    <div class="formats-grid" id="formatsGrid">
                        <!-- Format cards will be inserted here -->
                    </div>
                </div>
                
                <div class="download-section" id="downloadSection">
                    <div class="section-title">
                        <span>⬇️ Download Options</span>
                    </div>
                    
                    <div id="downloadMessage" style="color: #aaa; margin-bottom: 20px; text-align: center;">
                        Select a quality format above to enable download options
                    </div>
                    
                    <div class="download-options" id="downloadOptions" style="display: none;">
                        <div class="download-option">
                            <div class="option-icon">⚡</div>
                            <div class="option-title">Direct Download</div>
                            <div class="option-desc">Download immediately in your browser</div>
                            <button class="btn btn-primary" onclick="downloadDirect()" id="directBtn" style="width: 100%;">
                                Download Now
                            </button>
                        </div>
                        
                        <div class="download-option">
                            <div class="option-icon">🎬</div>
                            <div class="option-title">Stream Online</div>
                            <div class="option-desc">Watch directly in browser without downloading</div>
                            <button class="btn btn-success" onclick="streamVideo()" id="streamBtn" style="width: 100%;">
                                Stream Video
                            </button>
                        </div>
                        
                        <div class="download-option">
                            <div class="option-icon">📁</div>
                            <div class="option-title">Get Direct URL</div>
                            <div class="option-desc">Get the direct googlevideo.com link</div>
                            <button class="btn btn-secondary" onclick="getDirectURL()" id="urlBtn" style="width: 100%;">
                                Get URL
                            </button>
                        </div>
                    </div>
                    
                    <div class="progress-container" id="progressContainer">
                        <div class="progress-header">
                            <span>Download Progress</span>
                            <span id="progressPercent">0%</span>
                        </div>
                        <div class="progress-bar">
                            <div class="progress-fill" id="progressFill"></div>
                        </div>
                        <div class="progress-stats">
                            <span id="progressSpeed">Speed: 0 KB/s</span>
                            <span id="progressTime">Time left: --:--</span>
                        </div>
                    </div>
                    
                    <div class="url-display" id="urlDisplay">
                        <!-- Direct URL will be displayed here -->
                    </div>
                </div>
            </div>
        </div>
        
        <div class="features">
            <div class="feature-card">
                <div class="feature-icon">🔓</div>
                <div class="feature-title">No Limits</div>
                <div class="feature-desc">Download as many videos as you want, no restrictions or registration required.</div>
            </div>
            <div class="feature-card">
                <div class="feature-icon">🚀</div>
                <div class="feature-title">High Speed</div>
                <div class="feature-desc">Optimized for fast downloads using multiple connections and efficient streaming.</div>
            </div>
            <div class="feature-card">
                <div class="feature-icon">🎨</div>
                <div class="feature-title">All Qualities</div>
                <div class="feature-desc">From 144p to 4K, MP3 audio to highest video quality available.</div>
            </div>
            <div class="feature-card">
                <div class="feature-icon">🛡️</div>
                <div class="feature-title">Safe & Private</div>
                <div class="feature-desc">Your privacy is protected. We don't store any of your data or download history.</div>
            </div>
        </div>
        
        <footer>
            <p>© 2024 YouTube Downloader. For personal use only.</p>
            <p style="margin-top: 10px; color: #666; font-size: 0.85rem;">
                Disclaimer: Please respect copyright laws and only download videos you have permission to download.
            </p>
            <div class="footer-links">
                <a href="javascript:void(0)" onclick="showAbout()">About</a>
                <a href="javascript:void(0)" onclick="showPrivacy()">Privacy</a>
                <a href="javascript:void(0)" onclick="showTerms()">Terms</a>
                <a href="javascript:void(0)" onclick="showHelp()">Help</a>
            </div>
        </footer>
    </div>
    
    <script>
        let currentVideoId = '';
        let currentFormats = [];
        let selectedFormat = null;
        let currentDownloadId = null;
        
        // Initialize with example URL if needed
        function showExample() {
            document.getElementById('youtubeUrl').value = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
            getVideoInfo();
        }
        
        async function pasteFromClipboard() {
            try {
                const text = await navigator.clipboard.readText();
                document.getElementById('youtubeUrl').value = text;
            } catch (err) {
                showError('Failed to paste from clipboard. Please paste manually.');
            }
        }
        
        function clearInput() {
            document.getElementById('youtubeUrl').value = '';
            document.getElementById('resultSection').style.display = 'none';
            document.getElementById('error').style.display = 'none';
        }
        
        function getVideoInfo() {
            const url = document.getElementById('youtubeUrl').value.trim();
            const loading = document.getElementById('loading');
            const resultSection = document.getElementById('resultSection');
            const errorDiv = document.getElementById('error');
            const analyzeBtn = document.getElementById('analyzeBtn');
            
            if (!url) {
                showError('Please enter a YouTube URL');
                return;
            }
            
            // Validate URL
            if (!url.includes('youtube.com') && !url.includes('youtu.be')) {
                showError('Please enter a valid YouTube URL');
                return;
            }
            
            // Reset UI
            resultSection.style.display = 'none';
            errorDiv.style.display = 'none';
            loading.style.display = 'block';
            analyzeBtn.disabled = true;
            analyzeBtn.innerHTML = '<span>⏳ Processing...</span>';
            
            // Call API
            fetch(`/api/get-video-info?url=${encodeURIComponent(url)}`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Network response was not ok');
                    }
                    return response.json();
                })
                .then(data => {
                    loading.style.display = 'none';
                    analyzeBtn.disabled = false;
                    analyzeBtn.innerHTML = '<span>🔍 Analyze Video</span>';
                    
                    if (data.success) {
                        displayVideoInfo(data);
                    } else {
                        showError(data.error || 'Failed to get video information. The video might be private or restricted.');
                    }
                })
                .catch(error => {
                    loading.style.display = 'none';
                    analyzeBtn.disabled = false;
                    analyzeBtn.innerHTML = '<span>🔍 Analyze Video</span>';
                    showError('Network error. Please check your connection and try again.');
                    console.error('Error:', error);
                });
        }
        
        function displayVideoInfo(data) {
            const resultSection = document.getElementById('resultSection');
            const videoInfo = document.getElementById('videoInfo');
            const formatsGrid = document.getElementById('formatsGrid');
            const downloadSection = document.getElementById('downloadSection');
            const downloadOptions = document.getElementById('downloadOptions');
            const downloadMessage = document.getElementById('downloadMessage');
            
            currentVideoId = data.video_id;
            currentFormats = data.formats;
            selectedFormat = null;
            
            // Format views count
            const views = data.views ? formatNumber(data.views) : 'N/A';
            
            // Display video info
            videoInfo.innerHTML = `
                <div class="thumbnail-container">
                    <img src="${data.thumbnail}" alt="Thumbnail" class="video-thumbnail" onerror="this.src='https://i.ytimg.com/vi/${data.video_id}/hqdefault.jpg'">
                    ${data.duration ? `<div class="duration-badge">${data.duration}</div>` : ''}
                </div>
                <div class="video-details">
                    <h2 class="video-title">${data.title || 'Untitled Video'}</h2>
                    <div class="video-meta">
                        <span><strong>Channel:</strong> ${data.channel || 'Unknown'}</span>
                        <span>👁️ ${views} views</span>
                        ${data.duration ? `<span>⏱️ ${data.duration}</span>` : ''}
                    </div>
                    <div class="video-description">
                        ${data.description || 'No description available.'}
                    </div>
                    <div style="margin-top: 20px; color: #4CAF50; font-size: 0.9rem;">
                        ✅ ${data.formats.length} formats available
                    </div>
                </div>
            `;
            
            // Display formats
            filterFormats('all');
            
            // Reset download section
            downloadOptions.style.display = 'none';
            downloadMessage.style.display = 'block';
            document.getElementById('progressContainer').style.display = 'none';
            document.getElementById('urlDisplay').style.display = 'none';
            
            // Show result section
            resultSection.style.display = 'block';
            resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
        
        function filterFormats(filterType) {
            const formatsGrid = document.getElementById('formatsGrid');
            const filterBtns = document.querySelectorAll('.filter-btn');
            
            // Update active filter button
            filterBtns.forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
            
            // Filter formats
            let filteredFormats = [...currentFormats];
            
            switch(filterType) {
                case 'video+audio':
                    filteredFormats = currentFormats.filter(f => f.type === 'video+audio');
                    break;
                case 'video':
                    filteredFormats = currentFormats.filter(f => f.type === 'video');
                    break;
                case 'audio':
                    filteredFormats = currentFormats.filter(f => f.type === 'audio');
                    break;
                case 'hd':
                    filteredFormats = currentFormats.filter(f => {
                        if (f.type.includes('video')) {
                            const height = f.height || 0;
                            return height >= 720;
                        }
                        return false;
                    });
                    break;
            }
            
            // Display formats
            if (filteredFormats.length === 0) {
                formatsGrid.innerHTML = `
                    <div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: #666;">
                        <div style="font-size: 3rem; margin-bottom: 20px;">😕</div>
                        <h3>No formats found</h3>
                        <p>Try selecting a different filter or check if the video is available.</p>
                    </div>
                `;
                return;
            }
            
            let formatsHtml = '';
            filteredFormats.forEach((format, index) => {
                const isSelected = selectedFormat && selectedFormat.format_id === format.format_id;
                const isGooglevideo = format.is_googlevideo;
                
                formatsHtml += `
                    <div class="format-card ${isSelected ? 'selected' : ''}" 
                         onclick="selectFormat('${format.format_id}')">
                        <div class="format-header">
                            <div class="format-quality">${format.quality}</div>
                            <div class="format-badge">${format.type.toUpperCase()}</div>
                        </div>
                        
                        <div class="format-details">
                            <div class="detail-row">
                                <span class="detail-label">Format:</span>
                                <span class="detail-value">${format.extension.toUpperCase()}</span>
                            </div>
                            <div class="detail-row">
                                <span class="detail-label">Size:</span>
                                <span class="detail-value format-size">${format.size}</span>
                            </div>
                            ${format.width ? `
                                <div class="detail-row">
                                    <span class="detail-label">Resolution:</span>
                                    <span class="detail-value">${format.width}×${format.height}</span>
                                </div>
                            ` : ''}
                            ${format.fps ? `
                                <div class="detail-row">
                                    <span class="detail-label">FPS:</span>
                                    <span class="detail-value">${format.fps}</span>
                                </div>
                            ` : ''}
                            ${format.tbr ? `
                                <div class="detail-row">
                                    <span class="detail-label">Bitrate:</span>
                                    <span class="detail-value">${format.tbr}kbps</span>
                                </div>
                            ` : ''}
                        </div>
                        
                        ${format.vcodec || format.acodec ? `
                            <div class="format-codecs">
                                ${format.vcodec && format.vcodec !== 'none' ? `
                                    <span class="codec-badge">${format.vcodec.split('.')[0]}</span>
                                ` : ''}
                                ${format.acodec && format.acodec !== 'none' ? `
                                    <span class="codec-badge">${format.acodec.split('.')[0]}</span>
                                ` : ''}
                            </div>
                        ` : ''}
                        
                        <div style="margin-top: 15px; font-size: 0.8rem; color: ${isGooglevideo ? '#4CAF50' : '#FF9800'};">
                            ${isGooglevideo ? '✅ Direct googlevideo.com link' : '⚠️ May require processing'}
                        </div>
                    </div>
                `;
            });
            
            formatsGrid.innerHTML = formatsHtml;
        }
        
        function selectFormat(formatId) {
            selectedFormat = currentFormats.find(f => f.format_id === formatId);
            
            if (!selectedFormat) return;
            
            // Update UI
            document.querySelectorAll('.format-card').forEach(card => {
                card.classList.remove('selected');
            });
            event.target.closest('.format-card').classList.add('selected');
            
            // Show download options
            const downloadOptions = document.getElementById('downloadOptions');
            const downloadMessage = document.getElementById('downloadMessage');
            const directBtn = document.getElementById('directBtn');
            const streamBtn = document.getElementById('streamBtn');
            const urlBtn = document.getElementById('urlBtn');
            
            downloadOptions.style.display = 'grid';
            downloadMessage.style.display = 'none';
            
            // Update button texts
            directBtn.innerHTML = `⬇️ Download ${selectedFormat.quality}`;
            streamBtn.innerHTML = `▶️ Stream ${selectedFormat.quality}`;
            urlBtn.innerHTML = `🔗 Get ${selectedFormat.quality} URL`;
            
            // Scroll to download section
            document.getElementById('downloadSection').scrollIntoView({ 
                behavior: 'smooth', 
                block: 'start' 
            });
        }
        
        function downloadDirect() {
            if (!selectedFormat || !currentVideoId) {
                showError('Please select a format first');
                return;
            }
            
            // Open download in new tab
            const url = `/api/download-direct/${currentVideoId}?format=${selectedFormat.format_id}&quality=${encodeURIComponent(selectedFormat.quality)}`;
            window.open(url, '_blank');
        }
        
        function streamVideo() {
            if (!selectedFormat || !currentVideoId) {
                showError('Please select a format first');
                return;
            }
            
            // Open stream in new tab
            const url = `/api/stream/${currentVideoId}?format=${selectedFormat.format_id}`;
            window.open(url, '_blank');
        }
        
        async function getDirectURL() {
            if (!selectedFormat || !currentVideoId) {
                showError('Please select a format first');
                return;
            }
            
            const urlDisplay = document.getElementById('urlDisplay');
            urlDisplay.style.display = 'block';
            urlDisplay.innerHTML = '<div style="color: #aaa;">⏳ Getting direct URL...</div>';
            
            try {
                const response = await fetch(`/api/get-direct-url/${currentVideoId}?format=${selectedFormat.format_id}`);
                const data = await response.json();
                
                if (data.success && data.direct_url) {
                    // Display the URL
                    urlDisplay.innerHTML = `
                        <div style="margin-bottom: 10px; color: #4CAF50;">
                            ✅ Direct googlevideo.com URL (expires in 6 hours):
                        </div>
                        <div style="background: rgba(0,0,0,0.5); padding: 10px; border-radius: 5px; margin-bottom: 10px; font-size: 0.8rem;">
                            ${data.direct_url.substring(0, 100)}...
                        </div>
                        <button class="btn btn-secondary" onclick="copyToClipboard('${data.direct_url.replace(/'/g, "\\'")}')" style="width: 100%; margin-top: 10px;">
                            📋 Copy URL
                        </button>
                        <div style="margin-top: 10px; font-size: 0.8rem; color: #666;">
                            Use this URL in any download manager like IDM, wget, or curl
                        </div>
                    `;
                } else {
                    urlDisplay.innerHTML = '<div style="color: #FF9800;">⚠️ Could not get direct URL. Try downloading directly instead.</div>';
                }
            } catch (error) {
                urlDisplay.innerHTML = '<div style="color: #f44336;">❌ Error getting URL</div>';
            }
            
            urlDisplay.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        
        function copyToClipboard(text) {
            navigator.clipboard.writeText(text).then(() => {
                alert('URL copied to clipboard!');
            }).catch(err => {
                console.error('Failed to copy: ', err);
                alert('Failed to copy URL. Please copy manually.');
            });
        }
        
        function formatNumber(num) {
            if (num >= 1000000000) {
                return (num / 1000000000).toFixed(1) + 'B';
            }
            if (num >= 1000000) {
                return (num / 1000000).toFixed(1) + 'M';
            }
            if (num >= 1000) {
                return (num / 1000).toFixed(1) + 'K';
            }
            return num.toString();
        }
        
        function showError(message) {
            const errorDiv = document.getElementById('error');
            errorDiv.innerHTML = `
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 1.2rem;">❌</span>
                    <div>
                        <strong>Error:</strong> ${message}
                        <div style="margin-top: 5px; font-size: 0.9rem; color: rgba(255,255,255,0.7);">
                            Make sure the URL is correct and the video is publicly available.
                        </div>
                    </div>
                </div>
            `;
            errorDiv.style.display = 'block';
            errorDiv.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        
        // Allow Enter key to submit
        document.getElementById('youtubeUrl').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                getVideoInfo();
            }
        });
        
        // Demo info dialogs
        function showAbout() {
            alert('YouTube Downloader v2.0\n\nA free tool to download YouTube videos in any quality.\n\nFeatures:\n• All video qualities (144p to 4K)\n• Audio extraction (MP3)\n• Fast downloads\n• No registration required\n• Privacy focused');
        }
        
        function showPrivacy() {
            alert('Privacy Policy\n\nWe respect your privacy:\n• No user data is stored\n• No download history is kept\n• No cookies for tracking\n• All processing happens in real-time\n• No personal information required');
        }
        
        function showTerms() {
            alert('Terms of Use\n\n1. For personal use only\n2. Respect copyright laws\n3. Download only videos you have permission to download\n4. No commercial use\n5. Use at your own risk');
        }
        
        function showHelp() {
            alert('Help & Support\n\n1. Paste any YouTube URL\n2. Click "Analyze Video"\n3. Select your preferred quality\n4. Choose download method\n\nCommon issues:\n• Private videos cannot be downloaded\n• Age-restricted videos may not work\n• Check your internet connection\n• Try a different browser if issues persist');
        }
        
        // Auto-focus input on page load
        window.onload = function() {
            document.getElementById('youtubeUrl').focus();
        };
    </script>
</body>
</html>
'''

# ==================== API ENDPOINTS ====================

@app.route('/')
def home():
    """Home page with downloader interface"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/get-video-info', methods=['GET'])
def get_video_info():
    """Get video information and available formats"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({"success": False, "error": "URL parameter is required"}), 400
    
    video_id = YouTubeRealDownloader.extract_video_id(url)
    if not video_id:
        return jsonify({"success": False, "error": "Invalid YouTube URL"}), 400
    
    try:
        # Get video info
        video_info = YouTubeRealDownloader.get_video_info(video_id)
        
        if not video_info:
            return jsonify({"success": False, "error": "Could not fetch video information"}), 500
        
        # Format response
        response = {
            "success": True,
            "video_id": video_id,
            "title": video_info.get('title', 'Unknown Title'),
            "channel": video_info.get('channel', 'Unknown Channel'),
            "duration": video_info.get('duration', '0:00'),
            "views": video_info.get('views', 0),
            "description": video_info.get('description', ''),
            "thumbnail": video_info.get('thumbnail', f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'),
            "formats": video_info.get('formats', []),
            "format_count": len(video_info.get('formats', []))
        }
        
        return jsonify(response)
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/download-direct/<video_id>', methods=['GET'])
def download_direct(video_id):
    """Direct download endpoint"""
    format_id = request.args.get('format', 'best')
    quality = request.args.get('quality', 'Unknown')
    
    try:
        # Get real stream URL
        stream_info = YouTubeRealDownloader.get_real_stream_url(video_id, format_id)
        
        if not stream_info or not stream_info.get('url'):
            return jsonify({"success": False, "error": "Could not get download URL"}), 500
        
        # Get video info for filename
        video_info = YouTubeRealDownloader.get_video_info(video_id)
        title = video_info.get('title', f'video_{video_id}') if video_info else f'video_{video_id}'
        
        # Clean filename
        filename = re.sub(r'[^\w\-_\. ]', '_', title[:100])
        filename += f'_{quality}.{stream_info["ext"]}'
        
        # Stream download
        headers = {
            'User-Agent': USER_AGENT,
            'Accept': '*/*',
            'Accept-Encoding': 'identity',
            'Range': 'bytes=0-',
            'Referer': 'https://www.youtube.com/',
            'Origin': 'https://www.youtube.com'
        }
        
        def generate():
            with requests.get(stream_info['url'], headers=headers, stream=True, timeout=TIMEOUT) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=8192):
                    yield chunk
        
        # Determine content type
        content_type = 'video/mp4'
        if stream_info['ext'] == 'webm':
            content_type = 'video/webm'
        elif 'audio' in format_id:
            content_type = 'audio/mpeg'
        
        return Response(
            stream_with_context(generate()),
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': content_type,
                'Content-Length': str(stream_info.get('filesize', '')) if stream_info.get('filesize') else ''
            }
        )
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/stream/<video_id>', methods=['GET'])
def stream_video(video_id):
    """Stream video directly"""
    format_id = request.args.get('format', 'best')
    
    try:
        # Use yt-dlp to get stream URL
        stream_info = YouTubeRealDownloader.get_real_stream_url(video_id, format_id)
        
        if not stream_info or not stream_info.get('url'):
            return jsonify({"success": False, "error": "Could not get stream URL"}), 500
        
        # Stream with proper headers
        headers = {
            'User-Agent': USER_AGENT,
            'Accept': '*/*',
            'Accept-Encoding': 'identity',
            'Range': 'bytes=0-',
            'Referer': 'https://www.youtube.com/',
            'Origin': 'https://www.youtube.com'
        }
        
        response = requests.get(stream_info['url'], headers=headers, stream=True, timeout=TIMEOUT)
        
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                yield chunk
        
        # Determine content type
        content_type = 'video/mp4'
        if stream_info['ext'] == 'webm':
            content_type = 'video/webm'
        elif 'audio' in format_id:
            content_type = 'audio/mpeg'
        
        return Response(
            stream_with_context(generate()),
            content_type=content_type,
            headers={
                'Accept-Ranges': 'bytes',
                'Cache-Control': 'no-cache',
                'Content-Disposition': 'inline'
            }
        )
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/get-direct-url/<video_id>', methods=['GET'])
def get_direct_url(video_id):
    """Get direct googlevideo.com URL"""
    format_id = request.args.get('format', 'best')
    
    try:
        # Get real stream URL
        stream_info = YouTubeRealDownloader.get_real_stream_url(video_id, format_id)
        
        if not stream_info or not stream_info.get('url'):
            return jsonify({"success": False, "error": "Could not get direct URL"}), 500
        
        # Get video info for response
        video_info = YouTubeRealDownloader.get_video_info(video_id)
        
        return jsonify({
            "success": True,
            "video_id": video_id,
            "title": video_info.get('title', '') if video_info else 'Unknown',
            "quality": format_id,
            "direct_url": stream_info['url'],
            "url_length": len(stream_info['url']),
            "expires_in": "6 hours",
            "note": "This URL will expire. Use it quickly with download managers like IDM, wget, or curl."
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "YouTube Real Downloader",
        "version": "2.0",
        "timestamp": time.time(),
        "features": ["Direct downloads", "Streaming", "All qualities", "Audio extraction"]
    })

@app.route('/api/test-download/<video_id>', methods=['GET'])
def test_download(video_id):
    """Test endpoint to verify download works"""
    try:
        # Try to get video info
        video_info = YouTubeRealDownloader.get_video_info(video_id)
        
        if not video_info:
            return jsonify({"success": False, "error": "Video not found"}), 404
        
        # Try to get a stream URL
        stream_info = YouTubeRealDownloader.get_real_stream_url(video_id, '18')  # 360p
        
        return jsonify({
            "success": True,
            "video_id": video_id,
            "title": video_info.get('title', ''),
            "has_formats": len(video_info.get('formats', [])) > 0,
            "formats_count": len(video_info.get('formats', [])),
            "can_download": bool(stream_info and stream_info.get('url')),
            "sample_url_available": bool(stream_info),
            "url_length": len(stream_info['url']) if stream_info and 'url' in stream_info else 0,
            "is_googlevideo": 'googlevideo.com' in stream_info['url'] if stream_info and 'url' in stream_info else False
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

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
    print(f"🚀 YouTube Real Downloader starting on port {port}")
    print(f"🌐 Web Interface: http://localhost:{port}")
    print(f"🔧 API Test: http://localhost:{port}/api/test-download/dQw4w9WgXcQ")
    print(f"✅ Using yt-dlp for reliable downloads")
    app.run(host='0.0.0.0', port=port, debug=False)
