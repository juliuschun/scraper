# test_with_saving.py
import os
import sys
import time
import logging
from datetime import datetime
from main import ArticleScraper  # 실제 모듈명에 맞게 수정

# 테스트 URL 목록 (위에서 제공한 test_urls 전체 복사)
test_urls = {
    "조선일보": "https://www.chosun.com/economy/industry-company/2025/01/10/53UYCPNYXNCUZETTQXEO3ESDLI/",
    "중앙일보": "https://www.joongang.co.kr/article/25235095",
    "동아일보": "https://www.donga.com/news/Economy/article/all/20250110/130835500/1",
    "한겨레": "https://www.hani.co.kr/arti/economy/economy_general/1177260.html",
    "경향신문": "https://www.khan.co.kr/article/202501101358001",
    "MBC": "https://imnews.imbc.com/news/2025/econo/article/6675628_36737.html",
    "KBS": "https://news.kbs.co.kr/news/view.do?ncd=7878391",
    "SBS": "https://news.sbs.co.kr/news/endPage.do?news_id=N1007574671",
    "매일경제": "https://www.mk.co.kr/news/politics/10953645",
    "한국경제": "https://www.hankyung.com/article/2025011085857",
    "연합뉴스": "https://www.yna.co.kr/view/AKR20250110067700009?section=economy/international-economy",
    "뉴시스": "https://www.newsis.com/view/NISX20250110_0003027792",
    "노컷뉴스": "https://www.nocutnews.co.kr/news/6270582?page=1&c1=225",
    "오마이뉴스": "https://www.ohmynews.com/NWS_Web/View/at_pg.aspx?CNTN_CD=A0003095029",
    "국민일보": "https://www.kmib.co.kr/article/view.asp?arcid=1736411593&code=11151400&sid1=eco",
    "서울신문": "https://www.seoul.co.kr/news/newsView.php?id=20240322500094",
    "세계일보": "https://www.segye.com/newsView/20250110512479",
    "문화일보": "https://www.munhwa.com/news/view.html?no=2025011001070807207002",
    "머니투데이": "https://news.mt.co.kr/mtview.php?no=2025011011112051675&MT_T",
    "이데일리": "https://www.edaily.co.kr/News/Read?newsId=02499366642036408&mediaCodeNo=257"
}

# 저장 설정
SAVE_DIR = "articles"
os.makedirs(SAVE_DIR, exist_ok=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

COLORS = {
    "red": "\033[91m",
    "green": "\033[92m",
    "reset": "\033[0m"
}

def save_article(result: dict, site_name: str):
    """결과를 파일로 저장하는 함수"""
    try:
        # 파일명 생성 (도메인_타임스탬프)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{site_name}_{timestamp}.txt"
        filename = filename.replace(" ", "_").replace("/", "-")  # 파일명 정제
        
        filepath = os.path.join(SAVE_DIR, filename)
        
        # 메타데이터 + 본문 저장
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"제목: {result.get('title', 'N/A')}\n")
            f.write(f"작성자: {', '.join(result.get('authors', []))}\n")
            f.write(f"게시일: {result.get('publish_date', 'N/A')}\n")
            f.write(f"원본 URL: {result.get('url', 'N/A')}\n")
            f.write("\n" + "-"*50 + "\n")
            f.write(result.get('content', '콘텐츠를 추출하지 못했습니다.'))
            
        return filepath
    except Exception as e:
        logger.error(f"{COLORS['red']}파일 저장 실패: {str(e)}{COLORS['reset']}")
        return None

def test_scraper():
    scraper = ArticleScraper(headless=True)
    total = len(test_urls)
    passed = 0
    failed_urls = []
    total_time = 0

    logger.info(f"{'▶ 테스트 시작':^50}")
    
    for site_name, url in test_urls.items():
        try:
            start_time = time.time()
            result = scraper.extract_article_with_metadata(url)
            result['url'] = url  # URL 정보 추가
            elapsed = time.time() - start_time
            total_time += elapsed

            # 파일 저장 실행
            saved_path = save_article(result, site_name)
            
            # 결과 검증
            title_valid = bool(result.get('title'))
            content_valid = bool(result.get('content')) and len(result['content']) > 500
            
            if title_valid and content_valid:
                passed += 1
                status = f"{COLORS['green']}SUCCESS{COLORS['reset']}"
            else:
                failed_urls.append(url)
                status = f"{COLORS['red']}FAILED{COLORS['reset']}"

            # 결과 로깅
            logger.info(
                f"[{status}] {site_name}\n"
                f"  • 저장 위치: {saved_path or '없음'}\n"
                f"  • 처리 시간: {elapsed:.2f}s\n"
                f"  • 제목 유효성: {'✅' if title_valid else '❌'}\n"
                f"  • 본문 유효성: {'✅' if content_valid else '❌'}"
            )

        except Exception as e:
            failed_urls.append(url)
            logger.error(f"{COLORS['red']}[ERROR] {site_name} - {str(e)}{COLORS['reset']}")
            continue

    # 최종 리포트
    logger.info(f"\n{'▶ 테스트 결과':^50}")
    logger.info(f"총 테스트 URL: {total}")
    logger.info(f"저장 폴더: {os.path.abspath(SAVE_DIR)}")
    logger.info(f"성공: {passed} ({passed/total*100:.1f}%)")
    logger.info(f"실패: {total-passed} ({100-passed/total*100:.1f}%)")
    logger.info(f"평균 처리 시간: {total_time/total:.2f}s")

if __name__ == "__main__":
    test_scraper()