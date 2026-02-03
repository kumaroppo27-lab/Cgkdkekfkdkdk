import re
import json
import urllib.parse
import httpx
import asyncio
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import logging
from typing import Dict, List, Optional
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="YouTube Downloader - Exact Process",
    description="[START] से [END] तक का पूरा process",
    version="1.0.0",
    docs_url="/"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# HTTP Client
client = httpx.AsyncClient(
    timeout=30.0,
    headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
)

# ===================== STEP 1: START - User provides URL =====================
def validate_youtube_url(url: str) -> str:
    """Validate और Video ID extract करो"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=)([a-zA-Z0-9_-]{11})',
        r'(?:youtu\.be\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
        r'v=([a-zA-Z0-9_-]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    raise ValueError("Invalid YouTube URL")

# ===================== STEP 2: SCRAPE - Fetch YouTube HTML =====================
async def fetch_youtube_html(video_id: str) -> str:
    """YouTube पेज का HTML fetch करो"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    try:
        response = await client.get(url)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error(f"HTML fetch error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch YouTube page: {str(e)}")

# ===================== STEP 3: EXTRACT - Find ytInitialPlayerResponse =====================
def extract_player_response(html: str) -> Dict:
    """HTML में से ytInitialPlayerResponse ढूंढो"""
    patterns = [
        r'var ytInitialPlayerResponse\s*=\s*({.*?});\s*var',
        r'ytInitialPlayerResponse\s*=\s*({.*?});',
        r'window\["ytInitialPlayerResponse"\]\s*=\s*({.*?});',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                # Try to fix JSON
                json_str = match.group(1)
                json_str = re.sub(r',\s*}', '}', json_str)
                json_str = re.sub(r',\s*]', ']', json_str)
                return json.loads(json_str)
    
    raise ValueError("ytInitialPlayerResponse not found in HTML")

# ===================== STEP 4: PARSE - Get streamingData.formats =====================
def parse_streaming_data(player_response: Dict) -> List[Dict]:
    """streamingData से formats निकालो"""
    streaming_data = player_response.get('streamingData', {})
    
    formats = []
    
    # Regular formats
    for fmt in streaming_data.get('formats', []):
        formats.append(parse_format(fmt))
    
    # Adaptive formats (higher quality)
    for fmt in streaming_data.get('adaptiveFormats', []):
        formats.append(parse_format(fmt))
    
    return formats

def parse_format(fmt: Dict) -> Dict:
    """एक format की जानकारी parse करो"""
    return {
        'itag': fmt.get('itag'),
        'mimeType': fmt.get('mimeType', ''),
        'quality': fmt.get('qualityLabel', ''),
        'bitrate': fmt.get('bitrate', 0),
        'width': fmt.get('width'),
        'height': fmt.get('height'),
        'contentLength': fmt.get('contentLength'),
        'url': fmt.get('url'),
        'signatureCipher': fmt.get('signatureCipher') or fmt.get('cipher', ''),
        'hasAudio': 'audio' in (fmt.get('mimeType') or '').lower(),
        'hasVideo': 'video' in (fmt.get('mimeType') or '').lower(),
    }

# ===================== STEP 5: DECRYPT - Decode signatureCipher =====================
def decrypt_signature_cipher(cipher_text: str) -> Dict:
    """signatureCipher को decode करो"""
    if not cipher_text:
        return {}
    
    params = {}
    parts = cipher_text.split('&')
    
    for part in parts:
        if '=' in part:
            key, value = part.split('=', 1)
            params[key] = urllib.parse.unquote(value)
    
    return params

def decrypt_signature(encrypted_sig: str) -> str:
    """
    YouTube के encrypted signature को decrypt करो
    Note: यह simplified version है, असल में player.js से algorithm लेना पड़ता है
    """
    if not encrypted_sig:
        return ""
    
    # Basic operations (यूट्यूब हर दिन बदलता है इन्हें)
    operations = [
        ('reverse', None),  # String reverse
        ('slice', 3),       # First 3 characters remove
        ('swap', 1),        # Swap positions
    ]
    
    sig = encrypted_sig
    
    for op, param in operations:
        if op == 'reverse':
            sig = sig[::-1]
        elif op == 'slice' and param:
            sig = sig[param:]
        elif op == 'swap' and param:
            if param < len(sig):
                sig = sig[param] + sig[:param] + sig[param+1:]
    
    return sig

# ===================== STEP 6: CONSTRUCT - Build googlevideo.com URL =====================
def construct_download_url(base_url: str, signature: str, other_params: Dict) -> str:
    """googlevideo.com का डाउनलोड URL बनाओ"""
    if not base_url:
        return ""
    
    # URL parse करो
    if '?' in base_url:
        url_parts = base_url.split('?')
        base = url_parts[0]
        existing_params = urllib.parse.parse_qs(url_parts[1])
    else:
        base = base_url
        existing_params = {}
    
    # सभी parameters merge करो
    all_params = {}
    
    # Existing parameters
    for key, values in existing_params.items():
        if values:
            all_params[key] = values[0]
    
    # New parameters
    for key, value in other_params.items():
        if key not in ['url', 's', 'sp', 'sig']:
            all_params[key] = value
    
    # Signature add करो
    if signature:
        all_params['sig'] = signature
    
    # Final URL बनाओ
    query_string = urllib.parse.urlencode(all_params)
    return f"{base}?{query_string}"

# ===================== STEP 7: ENCODE - URL encode parameters =====================
def encode_url_parameters(url: str) -> str:
    """URL के special characters encode करो"""
    if not url:
        return ""
    
    # URL पहले से ही encoded हो सकता है
    try:
        # Decode पहले, फिर encode
        decoded = urllib.parse.unquote(url)
        # फिर से encode करो
        encoded = urllib.parse.quote(decoded, safe=':/?&=')
        return encoded
    except:
        return url

# ===================== STEP 8: RETURN - Provide download link =====================
def prepare_final_response(formats: List[Dict], video_info: Dict) -> Dict:
    """Final response तैयार करो"""
    # Video information
    video_details = video_info.get('videoDetails', {})
    
    # Available qualities
    qualities = []
    for fmt in formats:
        if fmt.get('height'):
            qualities.append({
                'quality': fmt['quality'],
                'itag': fmt['itag'],
                'has_url': bool(fmt.get('url')),
                'needs_decryption': bool(fmt.get('signatureCipher')),
                'size_mb': round(int(fmt.get('contentLength', 0)) / (1024*1024), 2) if fmt.get('contentLength') else None
            })
    
    # Remove duplicates
    unique_qualities = []
    seen = set()
    for q in qualities:
        key = q['quality']
        if key not in seen:
            seen.add(key)
            unique_qualities.append(q)
    
    # Best quality
    best_quality = max(
        [q for q in qualities if q.get('quality')],
        key=lambda x: int(x['quality'].replace('p', '')) if x['quality'].endswith('p') else 0,
        default=None
    )
    
    return {
        'video_info': {
            'id': video_details.get('videoId'),
            'title': video_details.get('title'),
            'duration_seconds': video_details.get('lengthSeconds'),
            'channel': video_details.get('author'),
            'views': video_details.get('viewCount'),
            'thumbnail': f"https://i.ytimg.com/vi/{video_details.get('videoId')}/maxresdefault.jpg"
        },
        'available_qualities': unique_qualities,
        'best_quality': best_quality,
        'total_formats': len(formats),
        'process_complete': True
    }

# ===================== STEP 9: END - User downloads video =====================
async def stream_video_download(download_url: str, filename: str) -> StreamingResponse:
    """Video stream करो user के लिए"""
    async def generator():
        async with httpx.AsyncClient() as stream_client:
            async with stream_client.stream('GET', download_url) as response:
                response.raise_for_status()
                
                # Headers send करो
                headers = f"Content-Disposition: attachment; filename=\"{filename}\"\n"
                headers += f"Content-Type: {response.headers.get('content-type', 'video/mp4')}\n\n"
                yield headers.encode()
                
                # Video data stream करो
                async for chunk in response.aiter_bytes():
                    yield chunk
    
    return StreamingResponse(
        generator(),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\"",
            "Content-Type": "video/mp4"
        }
    )

# ===================== MAIN PROCESS FUNCTION =====================
async def youtube_download_process(youtube_url: str, quality: str = "720p") -> Dict:
    """
    पूरा process एक function में
    [START] से [END] तक
    """
    process_steps = []
    
    try:
        # ===== STEP 1: START =====
        step1_start = time.time()
        video_id = validate_youtube_url(youtube_url)
        step1_time = time.time() - step1_start
        
        process_steps.append({
            'step': 1,
            'name': 'START - User provides URL',
            'status': 'completed',
            'time_taken': f"{step1_time:.2f}s",
            'data': {
                'video_id': video_id,
                'input_url': youtube_url
            }
        })
        
        # ===== STEP 2: SCRAPE =====
        step2_start = time.time()
        html_content = await fetch_youtube_html(video_id)
        html_size = len(html_content)
        step2_time = time.time() - step2_start
        
        process_steps.append({
            'step': 2,
            'name': 'SCRAPE - Fetch YouTube page HTML',
            'status': 'completed',
            'time_taken': f"{step2_time:.2f}s",
            'data': {
                'html_size_bytes': html_size,
                'html_size_kb': round(html_size / 1024, 2)
            }
        })
        
        # ===== STEP 3: EXTRACT =====
        step3_start = time.time()
        player_response = extract_player_response(html_content)
        step3_time = time.time() - step3_start
        
        process_steps.append({
            'step': 3,
            'name': 'EXTRACT - Find ytInitialPlayerResponse',
            'status': 'completed',
            'time_taken': f"{step3_time:.2f}s",
            'data': {
                'found_keys': list(player_response.keys()),
                'has_streaming_data': 'streamingData' in player_response
            }
        })
        
        # ===== STEP 4: PARSE =====
        step4_start = time.time()
        all_formats = parse_streaming_data(player_response)
        step4_time = time.time() - step4_start
        
        process_steps.append({
            'step': 4,
            'name': 'PARSE - Get streamingData.formats',
            'status': 'completed',
            'time_taken': f"{step4_time:.2f}s",
            'data': {
                'total_formats': len(all_formats),
                'formats_with_url': len([f for f in all_formats if f.get('url')]),
                'formats_with_cipher': len([f for f in all_formats if f.get('signatureCipher')])
            }
        })
        
        # ===== STEP 5: DECRYPT =====
        step5_start = time.time()
        decrypted_formats = []
        
        for fmt in all_formats:
            format_info = fmt.copy()
            
            if fmt.get('signatureCipher'):
                # Decrypt करो
                cipher_params = decrypt_signature_cipher(fmt['signatureCipher'])
                encrypted_sig = cipher_params.get('s', '')
                base_url = cipher_params.get('url', '')
                
                if encrypted_sig and base_url:
                    # Signature decrypt करो
                    decrypted_sig = decrypt_signature(encrypted_sig)
                    format_info['decrypted_signature'] = decrypted_sig
                    format_info['cipher_params'] = cipher_params
                else:
                    format_info['decryption_status'] = 'failed_no_cipher_data'
            else:
                format_info['decryption_status'] = 'not_needed'
            
            decrypted_formats.append(format_info)
        
        step5_time = time.time() - step5_start
        
        process_steps.append({
            'step': 5,
            'name': 'DECRYPT - Decode signatureCipher',
            'status': 'completed',
            'time_taken': f"{step5_time:.2f}s",
            'data': {
                'decrypted_formats': len([f for f in decrypted_formats if f.get('decrypted_signature')]),
                'decryption_success_rate': f"{len([f for f in decrypted_formats if f.get('decrypted_signature')]) / len(all_formats) * 100:.1f}%"
            }
        })
        
        # ===== STEP 6: CONSTRUCT =====
        step6_start = time.time()
        constructed_urls = []
        
        for fmt in decrypted_formats:
            if fmt.get('url'):
                # Direct URL है
                constructed_urls.append({
                    'itag': fmt['itag'],
                    'quality': fmt['quality'],
                    'url': fmt['url'],
                    'type': 'direct'
                })
            elif fmt.get('cipher_params') and fmt.get('decrypted_signature'):
                # Construct URL from cipher
                base_url = fmt['cipher_params'].get('url')
                signature = fmt['decrypted_signature']
                other_params = {k: v for k, v in fmt['cipher_params'].items() if k not in ['url', 's', 'sp']}
                
                if base_url and signature:
                    download_url = construct_download_url(base_url, signature, other_params)
                    constructed_urls.append({
                        'itag': fmt['itag'],
                        'quality': fmt['quality'],
                        'url': download_url,
                        'type': 'constructed'
                    })
        
        step6_time = time.time() - step6_start
        
        process_steps.append({
            'step': 6,
            'name': 'CONSTRUCT - Build googlevideo.com URL',
            'status': 'completed',
            'time_taken': f"{step6_time:.2f}s",
            'data': {
                'urls_constructed': len(constructed_urls),
                'direct_urls': len([u for u in constructed_urls if u['type'] == 'direct']),
                'constructed_urls': len([u for u in constructed_urls if u['type'] == 'constructed'])
            }
        })
        
        # ===== STEP 7: ENCODE =====
        step7_start = time.time()
        encoded_urls = []
        
        for url_info in constructed_urls:
            encoded_url = encode_url_parameters(url_info['url'])
            encoded_urls.append({
                **url_info,
                'encoded_url': encoded_url,
                'url_length': len(encoded_url)
            })
        
        step7_time = time.time() - step7_start
        
        process_steps.append({
            'step': 7,
            'name': 'ENCODE - URL encode parameters',
            'status': 'completed',
            'time_taken': f"{step7_time:.2f}s",
            'data': {
                'urls_encoded': len(encoded_urls),
                'avg_url_length': sum(u['url_length'] for u in encoded_urls) // len(encoded_urls) if encoded_urls else 0
            }
        })
        
        # ===== STEP 8: RETURN =====
        step8_start = time.time()
        final_response = prepare_final_response(all_formats, player_response)
        
        # Requested quality ढूंढो
        requested_quality = None
        for url_info in encoded_urls:
            if url_info['quality'] == quality or (quality == 'best' and url_info['quality'] == final_response['best_quality']['quality']):
                requested_quality = url_info
                break
        
        step8_time = time.time() - step8_start
        
        process_steps.append({
            'step': 8,
            'name': 'RETURN - Provide download link',
            'status': 'completed',
            'time_taken': f"{step8_time:.2f}s",
            'data': {
                'requested_quality': quality,
                'found_quality': requested_quality['quality'] if requested_quality else 'not_found',
                'download_available': bool(requested_quality)
            }
        })
        
        # ===== STEP 9: END =====
        total_time = time.time() - step1_start
        
        return {
            'process': 'YouTube Video Download Process',
            'status': 'COMPLETED',
            'total_time': f"{total_time:.2f}s",
            'steps': process_steps,
            'result': {
                'download_available': bool(requested_quality),
                'download_url': requested_quality['encoded_url'] if requested_quality else None,
                'quality': requested_quality['quality'] if requested_quality else None,
                'itag': requested_quality['itag'] if requested_quality else None,
                'video_info': final_response['video_info']
            },
            'available_qualities': final_response['available_qualities']
        }
        
    except Exception as e:
        logger.error(f"Process failed at step {len(process_steps) + 1}: {e}")
        
        # Failed step add करो
        process_steps.append({
            'step': len(process_steps) + 1,
            'name': f'STEP {len(process_steps) + 1} - FAILED',
            'status': 'failed',
            'error': str(e)
        })
        
        return {
            'process': 'YouTube Video Download Process',
            'status': 'FAILED',
            'failed_at_step': len(process_steps),
            'error': str(e),
            'steps': process_steps
        }

# ===================== API ENDPOINTS =====================
@app.get("/")
async def root():
    """API Home"""
    return {
        "message": "YouTube Download Process API",
        "process": "[START] से [END] तक का पूरा flow",
        "endpoints": {
            "/process": "पूरा process step-by-step देखें",
            "/download": "सीधे डाउनलोड करें",
            "/formats": "सभी formats देखें"
        }
    }

@app.get("/process")
async def show_full_process(url: str = Query(..., description="YouTube URL")):
    """
    पूरा process step-by-step दिखाएं
    """
    result = await youtube_download_process(url)
    return result

@app.get("/download")
async def download_video(
    url: str = Query(..., description="YouTube URL"),
    quality: str = Query("720p", description="Quality: 144p, 360p, 480p, 720p, 1080p, best")
):
    """
    सीधे video डाउनलोड करें
    """
    process_result = await youtube_download_process(url, quality)
    
    if process_result['status'] != 'COMPLETED':
        raise HTTPException(status_code=500, detail=process_result.get('error', 'Process failed'))
    
    if not process_result['result']['download_available']:
        raise HTTPException(status_code=404, detail=f"Quality {quality} not available")
    
    download_url = process_result['result']['download_url']
    video_title = process_result['result']['video_info']['title']
    safe_filename = re.sub(r'[^\w\s-]', '', video_title).strip().replace(' ', '_')
    final_filename = f"{safe_filename}_{quality}.mp4"
    
    # Stream the video
    async def stream_generator():
        async with httpx.AsyncClient() as stream_client:
            async with stream_client.stream('GET', download_url) as response:
                response.raise_for_status()
                
                # Headers
                yield f'Content-Disposition: attachment; filename="{final_filename}"\n'.encode()
                yield f'Content-Type: {response.headers.get("content-type", "video/mp4")}\n\n'.encode()
                
                # Video data
                async for chunk in response.aiter_bytes():
                    yield chunk
    
    return StreamingResponse(
        stream_generator(),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f"attachment; filename=\"{final_filename}\""
        }
    )

@app.get("/formats")
async def get_formats(url: str = Query(..., description="YouTube URL")):
    """सभी available formats देखें"""
    process_result = await youtube_download_process(url)
    
    if process_result['status'] != 'COMPLETED':
        raise HTTPException(status_code=500, detail=process_result.get('error', 'Process failed'))
    
    return {
        "video_info": process_result['result']['video_info'],
        "available_qualities": process_result['available_qualities'],
        "best_quality": process_result['result'].get('quality'),
        "process_summary": {
            "total_steps": len(process_result['steps']),
            "total_time": process_result['total_time'],
            "status": process_result['status']
        }
    }

@app.get("/debug")
async def debug_process(url: str = Query(..., description="YouTube URL")):
    """Debug information - सारे steps का detailed view"""
    try:
        # STEP 1
        video_id = validate_youtube_url(url)
        
        # STEP 2
        html = await fetch_youtube_html(video_id)
        
        # STEP 3
        player_response = extract_player_response(html)
        
        # STEP 4
        formats = parse_streaming_data(player_response)
        
        # एक format का detailed analysis
        sample_format = next((f for f in formats if f.get('signatureCipher')), None)
        
        decryption_info = None
        if sample_format and sample_format.get('signatureCipher'):
            # STEP 5
            cipher_params = decrypt_signature_cipher(sample_format['signatureCipher'])
            encrypted_sig = cipher_params.get('s', '')
            
            if encrypted_sig:
                decrypted_sig = decrypt_signature(encrypted_sig)
                
                # STEP 6
                base_url = cipher_params.get('url', '')
                other_params = {k: v for k, v in cipher_params.items() if k not in ['url', 's', 'sp']}
                constructed_url = construct_download_url(base_url, decrypted_sig, other_params)
                
                # STEP 7
                encoded_url = encode_url_parameters(constructed_url)
                
                decryption_info = {
                    'original_cipher': sample_format['signatureCipher'],
                    'cipher_params': cipher_params,
                    'encrypted_signature': encrypted_sig,
                    'decrypted_signature': decrypted_sig,
                    'base_url': base_url,
                    'constructed_url': constructed_url,
                    'encoded_url': encoded_url,
                    'url_length': len(encoded_url)
                }
        
        return {
            'video_id': video_id,
            'html_size': len(html),
            'player_response_keys': list(player_response.keys()),
            'total_formats': len(formats),
            'sample_format': sample_format,
            'decryption_process': decryption_info,
            'streaming_data_present': 'streamingData' in player_response,
            'formats_with_cipher': len([f for f in formats if f.get('signatureCipher')]),
            'formats_with_direct_url': len([f for f in formats if f.get('url') and not f.get('signatureCipher')])
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "process": "YouTube Download Flow",
        "steps": [
            "1. START - User provides URL",
            "2. SCRAPE - Fetch YouTube HTML",
            "3. EXTRACT - Find ytInitialPlayerResponse",
            "4. PARSE - Get streamingData.formats",
            "5. DECRYPT - Decode signatureCipher",
            "6. CONSTRUCT - Build googlevideo.com URL",
            "7. ENCODE - URL encode parameters",
            "8. RETURN - Provide download link",
            "9. END - User downloads video"
        ]
    }

@app.on_event("startup")
async def startup():
    """Startup event"""
    logger.info("YouTube Download Process API started")

@app.on_event("shutdown")
async def shutdown():
    """Shutdown event"""
    await client.aclose()
    logger.info("YouTube Download Process API stopped")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
