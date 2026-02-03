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

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
TIMEOUT = 30

class YouTubeHTMLParser:
    """Complete YouTube HTML Parser"""
    
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
    def fetch_youtube_html(video_id):
        """Fetch YouTube page HTML"""
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {
                'User-Agent': USER_AGENT,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            return response.text if response.status_code == 200 else None
        except:
            return None
    
    @staticmethod
    def parse_video_info(html):
        """Parse video information from HTML"""
        info = {
            'title': 'Unknown Title',
            'author': 'Unknown Channel',
            'description': '',
            'duration': '0:00',
            'views': '0',
            'publish_date': '',
            'likes': '0',
            'keywords': [],
            'category': '',
            'thumbnails': {}
        }
        
        try:
            # Extract title
            title_match = re.search(r'<meta name="title" content="([^"]+)"', html)
            if title_match:
                info['title'] = title_match.group(1)
            
            # Extract channel name
            channel_match = re.search(r'"author":"([^"]+)"', html)
            if channel_match:
                info['author'] = channel_match.group(1)
            
            # Extract description
            desc_match = re.search(r'"shortDescription":"([^"]*?)"', html)
            if desc_match:
                info['description'] = desc_match.group(1).replace('\\n', '\n')
            
            # Extract duration
            duration_match = re.search(r'"approxDurationMs":"(\d+)"', html)
            if duration_match:
                seconds = int(duration_match.group(1)) // 1000
                minutes = seconds // 60
                seconds = seconds % 60
                info['duration'] = f"{minutes}:{seconds:02d}"
            
            # Extract views
            views_match = re.search(r'"viewCount":"(\d+)"', html)
            if views_match:
                views = int(views_match.group(1))
                if views >= 1000000:
                    info['views'] = f"{views/1000000:.1f}M"
                elif views >= 1000:
                    info['views'] = f"{views/1000:.1f}K"
                else:
                    info['views'] = str(views)
            
            # Extract publish date
            date_match = re.search(r'"publishDate":"([^"]+)"', html)
            if date_match:
                info['publish_date'] = date_match.group(1)
            
            # Extract likes
            likes_match = re.search(r'"likeCount":"(\d+)"', html)
            if likes_match:
                info['likes'] = likes_match.group(1)
            
            # Extract keywords
            keywords_match = re.search(r'"keywords":\[(.*?)\]', html)
            if keywords_match:
                keywords_str = keywords_match.group(1)
                keywords = re.findall(r'"([^"]+)"', keywords_str)
                info['keywords'] = keywords
            
            # Extract category
            category_match = re.search(r'"category":"([^"]+)"', html)
            if category_match:
                info['category'] = category_match.group(1)
            
            return info
            
        except Exception as e:
            print(f"Error parsing video info: {e}")
            return info
    
    @staticmethod
    def extract_player_response(html):
        """Extract player response from HTML"""
        patterns = [
            r'var ytInitialPlayerResponse\s*=\s*({.*?});',
            r'ytInitialPlayerResponse\s*=\s*({.*?});',
            r'window\["ytInitialPlayerResponse"\]\s*=\s*({.*?});',
            r'ytInitialPlayerResponse\s*=\s*({.*?})\s*</script>',
            r'player_response":"({.*?})"'
        ]
        
        for pattern in patterns:
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
                    
                    # If it's base64 encoded in player_response pattern
                    if 'player_response' in pattern:
                        try:
                            decoded = base64.b64decode(json_str).decode('utf-8')
                            return json.loads(decoded)
                        except:
                            pass
                    
                    return json.loads(json_str)
                except json.JSONDecodeError as e:
                    print(f"JSON decode error: {e}")
                    continue
                except Exception as e:
                    print(f"Error extracting player response: {e}")
                    continue
        
        return None
    
    @staticmethod
    def extract_initial_data(html):
        """Extract initial data from HTML"""
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
                    return json.loads(json_str)
                except:
                    continue
        
        return None
    
    @staticmethod
    def extract_stream_urls(html):
        """Extract streaming URLs directly from HTML"""
        urls = []
        
        # Pattern 1: Direct googlevideo URLs
        patterns = [
            r'"url":"(https://[^"]*googlevideo\.com[^"]*videoplayback[^"]*)"',
            r'src="(https://[^"]*googlevideo\.com[^"]*videoplayback[^"]*)"',
            r'"(https://rr[^"]*googlevideo\.com[^"]*videoplayback[^"]*)"',
            r'\\"url\\":\\"(https://[^"]*googlevideo\.com[^"]*videoplayback[^"]*)\\"'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html)
            for match in matches:
                url = match.replace('\\/', '/').replace('\\u0026', '&').replace('\\\\"', '"')
                if 'googlevideo.com' in url and 'videoplayback' in url:
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
    def parse_streaming_formats(player_response):
        """Parse streaming formats from player response"""
        formats = []
        
        if not player_response:
            return formats
        
        try:
            streaming_data = player_response.get('streamingData', {})
            
            # Parse adaptive formats
            adaptive_formats = streaming_data.get('adaptiveFormats', [])
            for fmt in adaptive_formats:
                format_info = YouTubeHTMLParser.parse_individual_format(fmt)
                if format_info:
                    formats.append(format_info)
            
            # Parse progressive formats
            progressive_formats = streaming_data.get('formats', [])
            for fmt in progressive_formats:
                format_info = YouTubeHTMLParser.parse_individual_format(fmt)
                if format_info:
                    formats.append(format_info)
            
        except Exception as e:
            print(f"Error parsing streaming formats: {e}")
        
        return formats
    
    @staticmethod
    def parse_individual_format(fmt):
        """Parse individual format object"""
        try:
            # Get URL
            url = fmt.get('url', '')
            if not url and 'signatureCipher' in fmt:
                url = YouTubeHTMLParser.decode_cipher(fmt['signatureCipher'])
            
            if not url:
                return None
            
            # Get quality
            quality = fmt.get('qualityLabel', '')
            if not quality:
                if 'height' in fmt:
                    quality = f"{fmt['height']}p"
                elif 'bitrate' in fmt:
                    bitrate = fmt['bitrate']
                    if bitrate > 1000:
                        quality = f"{bitrate//1000}kbps"
                    else:
                        quality = f"{bitrate}bps"
                else:
                    quality = 'Unknown'
            
            # Get type
            mime_type = fmt.get('mimeType', 'video/mp4')
            
            # Determine if audio/video
            is_audio = 'audio' in mime_type.lower()
            is_video = 'video' in mime_type.lower() or 'mp4' in mime_type.lower()
            
            # Get size
            size_bytes = fmt.get('contentLength', 0)
            if size_bytes:
                try:
                    size_int = int(size_bytes)
                    if size_int >= 1024*1024*1024:
                        size = f"{size_int/(1024*1024*1024):.1f} GB"
                    elif size_int >= 1024*1024:
                        size = f"{size_int/(1024*1024):.1f} MB"
                    elif size_int >= 1024:
                        size = f"{size_int/1024:.1f} KB"
                    else:
                        size = f"{size_int} B"
                except:
                    size = "Unknown"
            else:
                size = "Unknown"
            
            # Get fps
            fps = fmt.get('fps', 0)
            
            # Get codec
            codec = 'Unknown'
            if 'codecs' in fmt:
                codec = fmt['codecs']
            elif 'audioQuality' in fmt:
                codec = fmt['audioQuality']
            
            return {
                'itag': fmt.get('itag', ''),
                'quality': quality,
                'type': mime_type,
                'url': url,
                'has_video': is_video,
                'has_audio': is_audio or (is_video and not is_audio),
                'size': size,
                'fps': fps,
                'codec': codec,
                'bitrate': fmt.get('bitrate', 0)
            }
            
        except Exception as e:
            print(f"Error parsing individual format: {e}")
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
            
            # Add signature if present
            sp = params.get('sp', 'signature')
            s = params.get('s', '')
            
            if s:
                # Simple signature appending
                url += f"&{sp}={s}"
            
            return url
            
        except:
            return None
    
    @staticmethod
    def get_thumbnails(video_id, initial_data):
        """Extract thumbnails"""
        thumbnails = {
            'default': f"https://i.ytimg.com/vi/{video_id}/default.jpg",
            'medium': f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
            'high': f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            'standard': f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
            'maxres': f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
        }
        
        # Try to get from initial data
        if initial_data:
            try:
                video_details = YouTubeHTMLParser.find_key(initial_data, 'videoDetails')
                if video_details and 'thumbnail' in video_details:
                    thumb_data = video_details['thumbnail']['thumbnails']
                    for thumb in thumb_data:
                        width = thumb.get('width', 0)
                        height = thumb.get('height', 0)
                        url = thumb.get('url', '')
                        
                        if width >= 1280 and height >= 720:
                            thumbnails['maxres'] = url
                        elif width >= 640 and height >= 480:
                            thumbnails['standard'] = url
                        elif width >= 480 and height >= 360:
                            thumbnails['high'] = url
                        elif width >= 320 and height >= 180:
                            thumbnails['medium'] = url
                        else:
                            thumbnails['default'] = url
            except:
                pass
        
        return thumbnails
    
    @staticmethod
    def find_key(obj, key):
        """Find key in nested dictionary"""
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for k, v in obj.items():
                result = YouTubeHTMLParser.find_key(v, key)
                if result:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = YouTubeHTMLParser.find_key(item, key)
                if result:
                    return result
        return None
    
    @staticmethod
    def get_comments(initial_data, limit=20):
        """Extract comments"""
        comments = []
        
        if not initial_data:
            return comments
        
        try:
            # Navigate to comments section
            continuation_items = YouTubeHTMLParser.find_key(initial_data, 'continuationItems')
            if continuation_items:
                for item in continuation_items:
                    if 'commentThreadRenderer' in item:
                        comment_renderer = item['commentThreadRenderer']
                        comment = comment_renderer.get('comment', {})
                        comment_renderer = comment.get('commentRenderer', {})
                        
                        author = comment_renderer.get('authorText', {}).get('simpleText', '')
                        content = comment_renderer.get('contentText', {}).get('simpleText', '')
                        
                        if author and content:
                            comments.append({
                                'author': author,
                                'content': content,
                                'likes': comment_renderer.get('likeCount', 0),
                                'time': comment_renderer.get('publishedTimeText', {}).get('simpleText', '')
                            })
                            
                            if len(comments) >= limit:
                                break
        
        except:
            pass
        
        return comments
    
    @staticmethod
    def get_related_videos(initial_data, limit=10):
        """Extract related videos"""
        related = []
        
        if not initial_data:
            return related
        
        try:
            # Find related videos
            secondary_results = YouTubeHTMLParser.find_key(initial_data, 'secondaryResults')
            if secondary_results and 'secondaryResults' in secondary_results:
                results = secondary_results['secondaryResults'].get('results', [])
                
                for item in results:
                    if 'compactVideoRenderer' in item:
                        video = item['compactVideoRenderer']
                        video_id = video.get('videoId', '')
                        title = video.get('title', {}).get('simpleText', '')
                        author = video.get('longBylineText', {}).get('simpleText', '')
                        
                        if video_id and title:
                            related.append({
                                'video_id': video_id,
                                'title': title,
                                'author': author,
                                'views': video.get('viewCountText', {}).get('simpleText', ''),
                                'duration': video.get('lengthText', {}).get('simpleText', ''),
                                'thumbnail': f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                            })
                            
                            if len(related) >= limit:
                                break
        
        except:
            pass
        
        return related

# ==================== ROUTES ====================

@app.route('/')
def home():
    return jsonify({
        "api": "YouTube HTML Parser API",
        "version": "1.0",
        "description": "Complete YouTube HTML parsing and downloading",
        "endpoints": {
            "/parse?url=YOUTUBE_URL": "Parse complete video information",
            "/download?url=YOUTUBE_URL&itag=ITAG": "Download video",
            "/stream?url=YOUTUBE_URL&itag=ITAG": "Stream video",
            "/thumbnails?url=YOUTUBE_URL": "Get thumbnails",
            "/comments?url=YOUTUBE_URL": "Get comments",
            "/related?url=YOUTUBE_URL": "Get related videos",
            "/raw-html?url=YOUTUBE_URL": "Get raw HTML (debug)",
            "/health": "Health check"
        }
    })

@app.route('/parse')
def parse_video():
    """Parse complete video information"""
    url = request.args.get('url', '')
    get_comments = request.args.get('comments', 'false').lower() == 'true'
    get_related = request.args.get('related', 'true').lower() == 'true'
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeHTMLParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Fetch HTML
    html = YouTubeHTMLParser.fetch_youtube_html(video_id)
    if not html:
        return jsonify({"error": "Could not fetch YouTube page"}), 500
    
    # Parse video info
    video_info = YouTubeHTMLParser.parse_video_info(html)
    
    # Extract player response
    player_response = YouTubeHTMLParser.extract_player_response(html)
    
    # Extract initial data
    initial_data = YouTubeHTMLParser.extract_initial_data(html)
    
    # Get thumbnails
    thumbnails = YouTubeHTMLParser.get_thumbnails(video_id, initial_data)
    
    # Get streaming formats
    formats = []
    if player_response:
        formats = YouTubeHTMLParser.parse_streaming_formats(player_response)
    
    # Also try direct URL extraction
    direct_urls = YouTubeHTMLParser.extract_stream_urls(html)
    
    # Get comments if requested
    comments = []
    if get_comments and initial_data:
        comments = YouTubeHTMLParser.get_comments(initial_data, limit=20)
    
    # Get related videos if requested
    related_videos = []
    if get_related and initial_data:
        related_videos = YouTubeHTMLParser.get_related_videos(initial_data, limit=10)
    
    # Prepare response
    response = {
        "success": True,
        "video_id": video_id,
        "info": video_info,
        "thumbnails": thumbnails,
        "formats": {
            "total": len(formats),
            "list": formats[:20],  # Limit to first 20
            "direct_urls_count": len(direct_urls)
        },
        "metadata": {
            "html_length": len(html),
            "has_player_response": bool(player_response),
            "has_initial_data": bool(initial_data),
            "parsing_time": time.time()
        }
    }
    
    if get_comments:
        response["comments"] = {
            "count": len(comments),
            "list": comments
        }
    
    if get_related:
        response["related_videos"] = {
            "count": len(related_videos),
            "list": related_videos
        }
    
    # Add download endpoints
    if formats:
        response["download_endpoints"] = []
        for fmt in formats[:5]:  # Add first 5 formats
            if fmt.get('url'):
                response["download_endpoints"].append({
                    "quality": fmt['quality'],
                    "itag": fmt['itag'],
                    "download": f"/download?url=https://youtube.com/watch?v={video_id}&itag={fmt['itag']}",
                    "stream": f"/stream?url=https://youtube.com/watch?v={video_id}&itag={fmt['itag']}"
                })
    
    return jsonify(response)

@app.route('/download')
def download_video():
    """Download video"""
    url = request.args.get('url', '')
    itag = request.args.get('itag', '')
    quality = request.args.get('quality', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeHTMLParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Fetch HTML
    html = YouTubeHTMLParser.fetch_youtube_html(video_id)
    if not html:
        return jsonify({"error": "Could not fetch video"}), 500
    
    # Extract player response
    player_response = YouTubeHTMLParser.extract_player_response(html)
    if not player_response:
        return jsonify({"error": "Could not extract video data"}), 500
    
    # Parse formats
    formats = YouTubeHTMLParser.parse_streaming_formats(player_response)
    
    # Find the requested format
    target_format = None
    if itag:
        for fmt in formats:
            if str(fmt.get('itag', '')) == str(itag):
                target_format = fmt
                break
    elif quality:
        for fmt in formats:
            if fmt.get('quality', '').lower() == quality.lower():
                target_format = fmt
                break
    
    # If no specific format requested, use first available
    if not target_format and formats:
        # Try to find a progressive format first
        for fmt in formats:
            if fmt.get('has_video') and fmt.get('has_audio'):
                target_format = fmt
                break
        
        # Then any format
        if not target_format:
            target_format = formats[0]
    
    if not target_format or not target_format.get('url'):
        return jsonify({
            "error": "No suitable format found",
            "available_formats": [{"itag": f.get('itag'), "quality": f.get('quality')} for f in formats]
        }), 404
    
    download_url = target_format['url']
    
    try:
        # Get video info for filename
        video_info = YouTubeHTMLParser.parse_video_info(html)
        title = video_info.get('title', f'video_{video_id}')
        
        # Clean filename
        filename = re.sub(r'[^\w\-_\. ]', '_', title[:50])
        
        # Add quality and extension
        if target_format['has_audio'] and not target_format['has_video']:
            filename += f"_audio_{target_format['quality']}.mp3"
            content_type = 'audio/mpeg'
        else:
            filename += f"_{target_format['quality']}.mp4"
            content_type = target_format.get('type', 'video/mp4')
        
        # Stream the download
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
                'Content-Type': content_type,
                'Content-Length': target_format.get('size', '')
            }
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stream')
def stream_video():
    """Stream video"""
    url = request.args.get('url', '')
    itag = request.args.get('itag', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeHTMLParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Fetch HTML
    html = YouTubeHTMLParser.fetch_youtube_html(video_id)
    if not html:
        return jsonify({"error": "Could not fetch video"}), 500
    
    # Extract player response
    player_response = YouTubeHTMLParser.extract_player_response(html)
    if not player_response:
        return jsonify({"error": "Could not extract video data"}), 500
    
    # Parse formats
    formats = YouTubeHTMLParser.parse_streaming_formats(player_response)
    
    # Find the requested format
    target_format = None
    if itag:
        for fmt in formats:
            if str(fmt.get('itag', '')) == str(itag):
                target_format = fmt
                break
    
    # If no specific format requested, find a good default
    if not target_format and formats:
        # Look for progressive format (video+audio)
        for fmt in formats:
            if fmt.get('has_video') and fmt.get('has_audio'):
                target_format = fmt
                break
        
        # Then look for any format
        if not target_format:
            target_format = formats[0]
    
    if not target_format or not target_format.get('url'):
        return jsonify({"error": "No streamable format found"}), 404
    
    stream_url = target_format['url']
    
    try:
        # Stream the video
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(stream_url, headers=headers, stream=True, timeout=TIMEOUT)
        
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                yield chunk
        
        content_type = target_format.get('type', 'video/mp4')
        
        return Response(
            stream_with_context(generate()),
            content_type=content_type,
            headers={
                'Cache-Control': 'no-cache',
                'Accept-Ranges': 'bytes',
                'Content-Length': target_format.get('size', '')
            }
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/thumbnails')
def get_thumbnails():
    """Get video thumbnails"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeHTMLParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Fetch HTML
    html = YouTubeHTMLParser.fetch_youtube_html(video_id)
    if not html:
        return jsonify({"error": "Could not fetch video"}), 500
    
    # Extract initial data
    initial_data = YouTubeHTMLParser.extract_initial_data(html)
    
    # Get thumbnails
    thumbnails = YouTubeHTMLParser.get_thumbnails(video_id, initial_data)
    
    return jsonify({
        "success": True,
        "video_id": video_id,
        "thumbnails": thumbnails
    })

@app.route('/comments')
def get_comments():
    """Get video comments"""
    url = request.args.get('url', '')
    limit = int(request.args.get('limit', 20))
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeHTMLParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Fetch HTML
    html = YouTubeHTMLParser.fetch_youtube_html(video_id)
    if not html:
        return jsonify({"error": "Could not fetch video"}), 500
    
    # Extract initial data
    initial_data = YouTubeHTMLParser.extract_initial_data(html)
    
    # Get comments
    comments = YouTubeHTMLParser.get_comments(initial_data, limit)
    
    return jsonify({
        "success": True,
        "video_id": video_id,
        "comments": {
            "count": len(comments),
            "list": comments
        }
    })

@app.route('/related')
def get_related():
    """Get related videos"""
    url = request.args.get('url', '')
    limit = int(request.args.get('limit', 10))
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeHTMLParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Fetch HTML
    html = YouTubeHTMLParser.fetch_youtube_html(video_id)
    if not html:
        return jsonify({"error": "Could not fetch video"}), 500
    
    # Extract initial data
    initial_data = YouTubeHTMLParser.extract_initial_data(html)
    
    # Get related videos
    related = YouTubeHTMLParser.get_related_videos(initial_data, limit)
    
    return jsonify({
        "success": True,
        "video_id": video_id,
        "related_videos": {
            "count": len(related),
            "list": related
        }
    })

@app.route('/raw-html')
def get_raw_html():
    """Get raw HTML (for debugging)"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    video_id = YouTubeHTMLParser.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Fetch HTML
    html = YouTubeHTMLParser.fetch_youtube_html(video_id)
    if not html:
        return jsonify({"error": "Could not fetch YouTube page"}), 500
    
    # Return first 5000 chars for debugging
    return Response(
        html[:5000],
        content_type='text/plain',
        headers={'Content-Disposition': f'inline; filename="{video_id}_html.txt"'}
    )

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "service": "YouTube HTML Parser API"
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting YouTube HTML Parser API on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
