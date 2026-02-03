from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import yt_dlp
import json
import asyncio
from typing import Optional, List, Dict
import httpx
import re
from pydantic import BaseModel
import time

app = FastAPI(
    title="YouTube Video Downloader API",
    description="YouTube से वीडियो और ऑडियो डाउनलोड करने का API",
    version="1.0.0",
    docs_url="/",
    redoc_url="/docs"
)

# CORS सेटअप (अगर Frontend से कनेक्ट करना है)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# मॉडल्स (Request/Response के लिए)
class VideoInfoRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    format_id: Optional[str] = None
    quality: Optional[str] = "720p"
    download_type: Optional[str] = "video"  # video, audio, or both

class VideoInfoResponse(BaseModel):
    title: str
    duration: int
    uploader: str
    views: int
    thumbnail: str
    formats: List[Dict]
    audio_formats: List[Dict]
    video_id: str

# Helper Functions
def extract_video_id(url: str) -> str:
    """YouTube URL से Video ID निकालना"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=)([a-zA-Z0-9_-]+)',
        r'(?:youtu\.be\/)([a-zA-Z0-9_-]+)',
        r'(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    raise HTTPException(status_code=400, detail="Invalid YouTube URL")

def sanitize_filename(filename: str) -> str:
    """फाइल नाम से विशेष characters हटाना"""
    return re.sub(r'[\\/*?:"<>|]', "", filename)

# API Endpoints

@app.get("/")
async def root():
    """API होम पेज"""
    return {
        "message": "YouTube Video Downloader API",
        "endpoints": {
            "GET /info?url=YOUTUBE_URL": "वीडियो की जानकारी प्राप्त करें",
            "GET /formats?url=YOUTUBE_URL": "सभी फॉर्मेट्स देखें",
            "GET /download?url=YOUTUBE_URL&format_id=FORMAT_ID": "वीडियो डाउनलोड करें",
            "GET /audio?url=YOUTUBE_URL": "ऑडियो डाउनलोड करें",
            "GET /thumbnail?url=YOUTUBE_URL": "थंबनेल प्राप्त करें"
        },
        "note": "YouTube Terms of Service का पालन करें"
    }

@app.get("/info")
async def get_video_info(url: str = Query(..., description="YouTube Video URL")):
    """
    YouTube वीडियो की सारी जानकारी प्राप्त करें
    """
    try:
        video_id = extract_video_id(url)
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'force_generic_extractor': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            formats = []
            audio_formats = []
            
            for fmt in info.get('formats', []):
                format_info = {
                    'format_id': fmt.get('format_id'),
                    'ext': fmt.get('ext'),
                    'resolution': fmt.get('resolution'),
                    'width': fmt.get('width'),
                    'height': fmt.get('height'),
                    'fps': fmt.get('fps'),
                    'filesize': fmt.get('filesize'),
                    'filesize_approx': fmt.get('filesize_approx'),
                    'vcodec': fmt.get('vcodec'),
                    'acodec': fmt.get('acodec'),
                    'abr': fmt.get('abr'),  # audio bitrate
                    'vbr': fmt.get('vbr'),  # video bitrate
                    'format_note': fmt.get('format_note'),
                    'url': fmt.get('url')
                }
                
                # Audio और Video फॉर्मेट्स अलग करना
                if fmt.get('acodec') != 'none' and fmt.get('vcodec') == 'none':
                    audio_formats.append(format_info)
                else:
                    formats.append(format_info)
            
            response = {
                "status": "success",
                "data": {
                    "video_id": video_id,
                    "title": info.get('title'),
                    "duration": info.get('duration'),
                    "uploader": info.get('uploader'),
                    "views": info.get('view_count'),
                    "thumbnail": info.get('thumbnail'),
                    "description": info.get('description'),
                    "upload_date": info.get('upload_date'),
                    "categories": info.get('categories', []),
                    "tags": info.get('tags', []),
                    "formats_count": len(formats) + len(audio_formats),
                    "formats": formats[:10],  # पहले 10 फॉर्मेट्स
                    "audio_formats": audio_formats[:10],  # पहले 10 ऑडियो फॉर्मेट्स
                    "best_video": max(
                        [f for f in formats if f.get('height')], 
                        key=lambda x: x.get('height', 0), 
                        default=None
                    ),
                    "best_audio": max(
                        audio_formats, 
                        key=lambda x: x.get('abr', 0), 
                        default=None
                    )
                }
            }
            
            return JSONResponse(content=response)
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching video info: {str(e)}")

@app.get("/formats")
async def get_all_formats(url: str = Query(..., description="YouTube Video URL")):
    """
    वीडियो के सभी उपलब्ध फॉर्मेट्स देखें
    """
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'list_formats': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            formats_by_quality = {}
            
            for fmt in info.get('formats', []):
                quality = fmt.get('format_note') or f"{fmt.get('height') or '?'}p"
                
                if quality not in formats_by_quality:
                    formats_by_quality[quality] = []
                
                format_info = {
                    'id': fmt.get('format_id'),
                    'extension': fmt.get('ext'),
                    'resolution': fmt.get('resolution'),
                    'video_codec': fmt.get('vcodec'),
                    'audio_codec': fmt.get('acodec'),
                    'filesize': fmt.get('filesize'),
                    'filesize_mb': round(fmt.get('filesize', 0) / (1024*1024), 2) if fmt.get('filesize') else None,
                    'bitrate': fmt.get('abr') or fmt.get('vbr'),
                    'type': 'audio' if fmt.get('vcodec') == 'none' else 'video',
                    'url': True if fmt.get('url') else False
                }
                
                formats_by_quality[quality].append(format_info)
            
            return {
                "status": "success",
                "video_title": info.get('title'),
                "total_formats": len(info.get('formats', [])),
                "formats_by_quality": formats_by_quality
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download")
async def download_video(
    url: str = Query(..., description="YouTube Video URL"),
    format_id: Optional[str] = Query(None, description="Format ID (itag)"),
    quality: Optional[str] = Query("720p", description="Quality like 360p, 720p, 1080p"),
    filename: Optional[str] = Query(None, description="Custom filename")
):
    """
    वीडियो डाउनलोड करें
    """
    try:
        video_id = extract_video_id(url)
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': format_id if format_id else f'best[height<={quality.replace("p", "")}]',
            'outtmpl': '%(title)s.%(ext)s',
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Best format select करें
            if not format_id:
                formats = info.get('formats', [])
                video_formats = [f for f in formats if f.get('vcodec') != 'none']
                
                if quality:
                    quality_num = int(quality.replace('p', ''))
                    selected_formats = [f for f in video_formats if f.get('height') == quality_num]
                    if selected_formats:
                        selected_format = selected_formats[0]
                    else:
                        selected_format = max(video_formats, key=lambda x: x.get('height', 0))
                else:
                    selected_format = max(video_formats, key=lambda x: x.get('height', 0))
                
                format_id = selected_format.get('format_id')
                ydl_opts['format'] = format_id
            
            # Download URL प्राप्त करें
            download_url = None
            for fmt in info.get('formats', []):
                if fmt.get('format_id') == format_id:
                    download_url = fmt.get('url')
                    break
            
            if not download_url:
                raise HTTPException(status_code=404, detail="Download URL not found")
            
            # फाइल नाम तय करें
            video_title = sanitize_filename(info.get('title', 'video'))
            if filename:
                final_filename = sanitize_filename(filename)
            else:
                final_filename = f"{video_title}_{quality or format_id}.mp4"
            
            # Streaming response भेजें
            async def stream_video():
                async with httpx.AsyncClient() as client:
                    async with client.stream('GET', download_url) as response:
                        response.raise_for_status()
                        yield f'Content-Disposition: attachment; filename="{final_filename}"\n\n'.encode()
                        async for chunk in response.aiter_bytes():
                            yield chunk
            
            return StreamingResponse(
                stream_video(),
                media_type="video/mp4",
                headers={
                    "Content-Disposition": f'attachment; filename="{final_filename}"',
                    "Cache-Control": "no-cache"
                }
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download error: {str(e)}")

@app.get("/audio")
async def download_audio(
    url: str = Query(..., description="YouTube Video URL"),
    bitrate: Optional[str] = Query("128", description="Audio bitrate (64, 128, 192, 256)"),
    format_type: Optional[str] = Query("mp3", description="Audio format (mp3, m4a, opus)")
):
    """
    ऑडियो डाउनलोड करें (MP3/M4A)
    """
    try:
        video_id = extract_video_id(url)
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': format_type,
                'preferredquality': bitrate,
            }],
            'outtmpl': '%(title)s.%(ext)s',
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # ऑडियो फॉर्मेट ढूंढें
            audio_formats = [f for f in info.get('formats', []) if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
            
            if not audio_formats:
                raise HTTPException(status_code=404, detail="No audio formats available")
            
            # Best audio select करें
            best_audio = max(audio_formats, key=lambda x: x.get('abr', 0))
            download_url = best_audio.get('url')
            
            if not download_url:
                raise HTTPException(status_code=404, detail="Audio URL not found")
            
            # फाइल नाम
            title = sanitize_filename(info.get('title', 'audio'))
            final_filename = f"{title}_{bitrate}kbps.{format_type}"
            
            # Stream audio
            async def stream_audio():
                async with httpx.AsyncClient() as client:
                    async with client.stream('GET', download_url) as response:
                        response.raise_for_status()
                        yield f'Content-Disposition: attachment; filename="{final_filename}"\n\n'.encode()
                        async for chunk in response.aiter_bytes():
                            yield chunk
            
            return StreamingResponse(
                stream_audio(),
                media_type="audio/mpeg" if format_type == "mp3" else "audio/mp4",
                headers={
                    "Content-Disposition": f'attachment; filename="{final_filename}"'
                }
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audio download error: {str(e)}")

@app.get("/thumbnail")
async def get_thumbnails(url: str = Query(..., description="YouTube Video URL")):
    """
    वीडियो के सभी थंबनेल प्राप्त करें
    """
    try:
        video_id = extract_video_id(url)
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            thumbnails = info.get('thumbnails', [])
            
            # विभिन्न साइज के थंबनेल
            thumbnail_dict = {}
            for thumb in thumbnails:
                res = f"{thumb.get('width', 0)}x{thumb.get('height', 0)}"
                thumbnail_dict[res] = thumb.get('url')
            
            # Default YouTube thumbnail URLs
            default_thumbnails = {
                "maxres": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
                "hq": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "mq": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
                "sd": f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
                "default": f"https://i.ytimg.com/vi/{video_id}/default.jpg"
            }
            
            # Combine both
            all_thumbnails = {**default_thumbnails, **thumbnail_dict}
            
            return {
                "status": "success",
                "video_id": video_id,
                "title": info.get('title'),
                "thumbnails": all_thumbnails,
                "best_thumbnail": max(
                    thumbnails, 
                    key=lambda x: x.get('width', 0) * x.get('height', 0),
                    default={"url": default_thumbnails["maxres"]}
                )['url']
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/search")
async def search_youtube(
    query: str = Query(..., description="Search query"),
    limit: int = Query(10, description="Number of results")
):
    """
    YouTube पर वीडियो सर्च करें
    """
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'force_generic_extractor': False,
        }
        
        search_query = f"ytsearch{limit}:{query}"
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)
            
            results = []
            for entry in info.get('entries', []):
                results.append({
                    'video_id': entry.get('id'),
                    'title': entry.get('title'),
                    'duration': entry.get('duration'),
                    'uploader': entry.get('uploader'),
                    'view_count': entry.get('view_count'),
                    'url': f"https://youtube.com/watch?v={entry.get('id')}",
                    'thumbnail': entry.get('thumbnail')
                })
            
            return {
                "status": "success",
                "query": query,
                "total_results": len(results),
                "results": results
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")

@app.get("/health")
async def health_check():
    """API हेल्थ चेक"""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "service": "YouTube Downloader API"
    }

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """कस्टम error response"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "message": exc.detail,
            "timestamp": time.time()
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
