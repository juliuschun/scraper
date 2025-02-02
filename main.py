import requests
from bs4 import BeautifulSoup
from newspaper import Article
from readability import Document
import trafilatura
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import time
import logging
from fastapi import FastAPI, HTTPException, BackgroundTasks
from typing import List, Optional
import asyncio
import json
from urllib.parse import urlparse
import re
import chardet
import random
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor
import functools
import redis
from datetime import timedelta
import hashlib
import os

class ArticleScraper:
    def __init__(self, headless=True, use_proxy=False, max_workers=30, cache_enabled=True):
        self.USER_AGENTS = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0.6099.119 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0',
            'Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36',
            'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36'
        ]
        self.headers = {
            'User-Agent': random.choice(self.USER_AGENTS)
        }
        self.headless = headless
        self.use_proxy = use_proxy
        self.setup_logging()
        
        # 도메인별 커스텀 설정
        self.custom_encodings = {
            'kmib.co.kr': 'cp949',
            'seoul.co.kr': 'euc-kr',
            'donga.com': 'cp949',
            'hankyung.com': 'utf-8'
        }
        
        self.fast_extract_domains = {
            'mk.co.kr': self._extract_with_trafilatura,
            'chosun.com': self._extract_with_trafilatura,
            'hankyung.com': self._extract_with_trafilatura,
        }

        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.semaphore = asyncio.Semaphore(max_workers)
        self.cache_enabled = cache_enabled
        self.redis_client = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=0,
            decode_responses=True
        )
        self.cache_ttl = timedelta(hours=24)  # 캐시 유효기간 24시간

    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def setup_selenium(self):
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument(f"user-agent={random.choice(self.USER_AGENTS)}")
        
        if self.use_proxy:
            chrome_options.add_argument(f'--proxy-server={self.get_proxy()}')
        
        return webdriver.Chrome(options=chrome_options)

    def get_proxy(self):
        return 'http://your-proxy:port'

    def detect_encoding(self, response):
        """향상된 인코딩 감지 로직"""
        domain = urlparse(response.url).netloc
        if domain in self.custom_encodings:
            return self.custom_encodings[domain]
        
        # 1. HTTP 헤더에서 인코딩 추출
        header_encoding = response.encoding
        if header_encoding.lower() in ['euc-kr', 'cp949']:
            return 'cp949'

        # 2. HTML meta 태그에서 인코딩 추출
        soup = BeautifulSoup(response.content[:2000], 'html.parser')
        meta_encoding = soup.find('meta', charset=True)
        if meta_encoding:
            return meta_encoding['charset'].lower()

        # 3. chardet으로 컨텐츠 분석
        detector = chardet.UniversalDetector()
        for chunk in response.iter_content(chunk_size=1000):
            detector.feed(chunk)
            if detector.done: break
        detector.close()
        
        detected = detector.result.get('encoding', '').lower()
        if detected in ['euc-kr', 'ks_c_5601-1987']:
            return 'cp949'
        
        return detected or 'utf-8'

    def safe_decode(self, content, encoding):
        """안전한 디코딩을 위한 래퍼 함수"""
        try:
            return content.decode(encoding, errors='replace')
        except UnicodeDecodeError:
            try:
                return content.decode('cp949', errors='replace')
            except:
                return content.decode('utf-8', errors='replace')

    def is_javascript_required(self, static_content, url):
        indicators = ["You need to enable JavaScript", "<noscript>", "javascript:void(0)"]
        if any(indicator in static_content for indicator in indicators):
            return True
            
        soup = BeautifulSoup(static_content, 'html.parser')
        article_content = soup.find_all(['p', 'article', 'div'], class_=['article', 'content', 'story'])
        return len(article_content) < 3

    def get_js_rendered_content(self, url, timeout=30):
        driver = None
        try:
            driver = self.setup_selenium()
            self.logger.info(f"JavaScript 렌더링 시작: {url}")
            driver.get(url)
            
            content_selectors = ["article", ".article-content", ".story-content", "main", "#main-content"]
            for selector in content_selectors:
                try:
                    WebDriverWait(driver, timeout).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    break
                except TimeoutException:
                    continue
            
            self.scroll_page(driver)
            return driver.page_source
            
        except Exception as e:
            self.logger.error(f"JavaScript 렌더링 실패: {e}")
            return None
        finally:
            if driver:
                driver.quit()

    def scroll_page(self, driver):
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.2)

    def is_paywall(self, content):
        paywall_indicators = {
            'phrases': ["subscribe to continue", "premium content", "sign up to read"],
            'elements': ['.paywall', '.subscription-required', '#piano-paywall']
        }
        
        soup = BeautifulSoup(content, 'html.parser')
        text_content = soup.get_text().lower()
        if any(phrase in text_content for phrase in paywall_indicators['phrases']):
            return True
            
        for element in paywall_indicators['elements']:
            if soup.select(element):
                return True
                
        return False

    def extract_title(self, soup, url):
        """개선된 제목 추출 메서드"""
        # 메타 태그에서 추출
        meta_selectors = [
            ('meta[property="og:title"]', 'content'),
            ('meta[name="title"]', 'content'),
            ('meta[property="twitter:title"]', 'content'),
            ('title', None)  # <title> 태그 직접 추출
        ]
        
        for selector, attr in meta_selectors:
            element = soup.select_one(selector)
            if element:
                title = element.get(attr, '').strip() if attr else element.get_text().strip()
                if title:
                    return title

        # HTML 구조 기반 추출
        html_selectors = [
            'h1', 'h2', 
            'h1.title', 'h1.article-title', 'h1.headline',
            '.article-header h1', '#article_title'
        ]
        
        for selector in html_selectors:
            element = soup.select_one(selector)
            if element and element.get_text().strip():
                return element.get_text().strip()

        # 도메인별 커스텀 추출
        domain = urlparse(url).netloc.lower()
        custom_selectors = {
            'chosun.com': ['h1.news-title', 'h1.article-title'],
            'joongang.co.kr': ['h1.headline'],
            'donga.com': ['h1.title'],
            'mk.co.kr': ['h1.top_title'],
            'hankyung.com': ['h1.title']
        }
        
        for site, selectors in custom_selectors.items():
            if site in domain:
                for selector in selectors:
                    element = soup.select_one(selector)
                    if element:
                        return element.get_text().strip()

        # newspaper3k 폴백
        try:
            article = Article(url)
            article.download()
            article.parse()
            return article.title
        except:
            return "[제목을 찾을 수 없음]"

    def clean_title(self, title):
        """제목 정제 메서드"""
        if not title:
            return ""
        
        # HTML 태그 제거
        cleanr = re.compile('<.*?>')
        title = re.sub(cleanr, '', title)
        
        # 특수 문자 및 불필요한 공백 제거
        title = re.sub(r'[\n\t\r]', ' ', title)  # 개행 문자 제거
        title = re.sub(r'\s{2,}', ' ', title)     # 다중 공백 단일화
        title = re.sub(r'[^\w\s-]', '', title)    # 특수 문자 제거
        return title.strip()

    def _extract_with_trafilatura(self, content):
        try:
            return trafilatura.extract(content, include_comments=False)
        except:
            return None

    def extract_article(self, url):
        try:
            response = requests.get(url, headers=self.headers)
            encoding = self.detect_encoding(response)
            decoded_content = self.safe_decode(response.content, encoding)
            
            if self.is_javascript_required(decoded_content, url):
                content = self.get_js_rendered_content(url) or decoded_content
            else:
                content = decoded_content
                
            if self.is_paywall(content):
                return None
                
            return self._clean_content(trafilatura.extract(content) or Article(url).text)
            
        except Exception as e:
            self.logger.error(f"기사 추출 실패: {e}")
            return None

    def extract_article_with_metadata(self, url, retry=3):
        for attempt in range(retry):
            try:
                # 단일 requests 요청으로 시작
                response = requests.get(url, headers=self.headers)
                encoding = self.detect_encoding(response)
                decoded_content = self.safe_decode(response.content, encoding)
                
                # 1. trafilatura로 먼저 시도
                content = self._extract_with_trafilatura(decoded_content)
                
                # 2. BeautifulSoup으로 기본 파싱
                soup = BeautifulSoup(decoded_content, 'html.parser', from_encoding=encoding)
                title = self.extract_title(soup, url)
                title = self.clean_title(title)
                
                # 3. content가 없거나 너무 짧은 경우에만 추가 처리
                if not content or len(content.split()) < 50:
                    # JavaScript 필요 여부 확인
                    if self.is_javascript_required(decoded_content, url):
                        js_content = self.get_js_rendered_content(url)
                        if js_content:
                            content = self._extract_with_trafilatura(js_content)
                    
                    # 여전히 content가 없는 경우 newspaper3k 시도
                    if not content:
                        article = Article(url)
                        try:
                            article.download()
                            article.parse()
                            content = article.text
                        except Exception as e:
                            self.logger.error(f"Article download failed: {str(e)}")
                
                # 저자 정보 추출
                domain = urlparse(url).netloc.lower()
                authors = []
                if 'chosun.com' in domain:
                    authors = [e.get_text().strip() for e in soup.select('.author')]
                elif 'mk.co.kr' in domain:
                    authors = [e.get_text().strip() for e in soup.select('.author_text')]
                
                result = {
                    'title': title,
                    'authors': authors,
                    'publish_date': None,  # 필요한 경우에만 추가 파싱
                    'content': self._clean_content(content)
                }
                
                return result
                
            except UnicodeDecodeError as e:
                alt_encodings = ['cp949', 'utf-8', 'euc-kr']
                current_idx = alt_encodings.index(encoding) if encoding in alt_encodings else -1
                next_encoding = alt_encodings[(current_idx + 1) % len(alt_encodings)] if current_idx != -1 else 'cp949'
                
                self.logger.warning(f"인코딩 재시도: {encoding} → {next_encoding}")
                response.encoding = next_encoding
                continue
            except Exception as e:
                self.logger.error(f"메타데이터 추출 실패: {e}")
                raise

    def _clean_content(self, text):
        if not text:
            return ""
        return re.sub(r'\s+', ' ', text).strip()

    def _get_cache_key(self, url):
        """URL에 대한 고유한 캐시 키 생성"""
        return f"article:{hashlib.md5(url.encode()).hexdigest()}"

    async def extract_article_with_metadata_async(self, url, retry=3):
        if self.cache_enabled:
            # 캐시 확인
            cache_key = self._get_cache_key(url)
            cached_data = self.redis_client.get(cache_key)
            if cached_data:
                try:
                    return json.loads(cached_data)
                except json.JSONDecodeError:
                    self.redis_client.delete(cache_key)

        # 캐시가 없으면 실제 스크래핑 수행
        async with self.semaphore:
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self.executor,
                    functools.partial(self.extract_article_with_metadata, url, retry)
                )
                
                # 결과 캐싱
                if self.cache_enabled and result:
                    cache_key = self._get_cache_key(url)
                    try:
                        self.redis_client.setex(
                            cache_key,
                            self.cache_ttl,
                            json.dumps(result)
                        )
                    except Exception as e:
                        self.logger.error(f"캐시 저장 실패: {e}")
                
                return result
            except Exception as e:
                self.logger.error(f"기사 추출 실패: {e}")
                raise

# FastAPI 앱
app = FastAPI(title="Advanced Article Scraper")
scraper = ArticleScraper(headless=True)

@app.get("/scrape")
async def scrape_metadata(url: str):
    try:
        result = scraper.extract_article_with_metadata(url)
        if not result.get('content'):
            raise HTTPException(400, detail="콘텐츠 추출 실패")
        return result
    except Exception as e:
        raise HTTPException(500, detail=str(e))

class URLList(BaseModel):
    urls: List[str]

@app.post("/scrape-multiple")
async def scrape_multiple(
    url_list: URLList,
    background_tasks: BackgroundTasks,
    skip_cache: bool = False
):
    if len(url_list.urls) > 100:
        raise HTTPException(400, "최대 100개의 URL만 처리 가능합니다")
    
    # 캐시 사용 여부 설정
    original_cache_setting = scraper.cache_enabled
    if skip_cache:
        scraper.cache_enabled = False
    
    try:
        tasks = [
            scraper.extract_article_with_metadata_async(url)
            for url in url_list.urls
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        formatted_results = []
        for url, result in zip(url_list.urls, results):
            if isinstance(result, Exception):
                formatted_results.append({
                    "url": url,
                    "success": False,
                    "error": str(result),
                    "cached": False
                })
            else:
                formatted_results.append({
                    "url": url,
                    "success": True,
                    "data": result,
                    "cached": not skip_cache and scraper.cache_enabled
                })
        
        return formatted_results
        
    except Exception as e:
        raise HTTPException(500, detail=str(e))
    finally:
        # 원래 캐시 설정 복구
        scraper.cache_enabled = original_cache_setting

# Redis 헬스체크 엔드포인트
@app.get("/health/cache")
async def check_cache_health():
    try:
        scraper.redis_client.ping()
        return {"status": "healthy", "cache": "connected"}
    except redis.ConnectionError:
        raise HTTPException(503, detail="Cache service unavailable")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("python:app", host="0.0.0.0", port=8099, reload=True)