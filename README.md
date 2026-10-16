# AI 유튜브 인기 영상 수집기

AI로 만든 유튜브 영상을 키워드별로 조회수 순으로 모아 CSV로 저장합니다.
Python 3만 있으면 되고, 따로 설치할 패키지는 없습니다.

## 1. YouTube API 키 발급 (최초 1회, 약 5분)

1. https://console.cloud.google.com 에 Google 계정으로 로그인
2. 상단 프로젝트 선택 → **새 프로젝트** → 이름 입력(예: `youtube-research`) → 만들기
3. 왼쪽 메뉴 **API 및 서비스 → 라이브러리** → `YouTube Data API v3` 검색 → **사용**
4. **API 및 서비스 → 사용자 인증 정보** → **+ 사용자 인증 정보 만들기 → API 키**
5. 생성된 키 복사
6. (권장) 키 옆 **수정** → *API 제한사항*에서 `YouTube Data API v3`만 선택 → 저장

> 무료이며 결제 정보 없이 사용할 수 있습니다. 하루 10,000 유닛까지 무료입니다.

## 2. 키 설정

API 키는 `config/` 폴더의 JSON 파일로 관리합니다.

```bash
cp config/google_api_keys.json.example config/google_api_keys.json
```

`config/google_api_keys.json` 파일을 열어 키를 넣습니다.

```json
{
  "youtube_api_key": "발급받은_API_키"
}
```

## 3. 실행

기본 실행 (AI 관련 키워드 8개, 최근 90일):

```bash
python3 youtube_ai_trends.py
```

한국 영상만, 최근 30일:

```bash
python3 youtube_ai_trends.py --region KR --lang ko --days 30
```

원하는 키워드로 Shorts만, 아웃라이어 비율 순 정렬:

```bash
python3 youtube_ai_trends.py -k "AI 고양이" "AI ASMR" "Veo 3" --shorts-only --sort outlier_ratio
```

결과는 `results/` 폴더에 CSV로 저장되며 엑셀에서 바로 열 수 있습니다.

## 옵션

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `-k`, `--keywords` | 검색 키워드 (여러 개, 공백 포함 시 따옴표) | AI 키워드 8개 |
| `--days` | 최근 며칠 이내 업로드 | 90 |
| `--max` | 키워드당 최대 영상 수 | 50 |
| `--region` | 국가 코드 (KR, US, JP…) | 전체 |
| `--lang` | 언어 코드 (ko, en…) | 전체 |
| `--shorts-only` | 3분 이하 Shorts만 | 끔 |
| `--sort` | `views` / `outlier_ratio` / `views_per_day` | views |
| `-o`, `--output` | CSV 저장 경로 | results/ai_videos_날짜.csv |

## CSV 컬럼 보는 법

- **outlier_ratio**: 조회수 ÷ 구독자 수. **10 이상**이면 채널 규모와 상관없이 포맷 자체가 터진 영상이라 따라 해볼 가치가 큽니다.
- **views_per_day**: 하루 평균 조회수. 최근 영상끼리 비교할 때 유용합니다.
- **like_rate_%**: 좋아요 ÷ 조회수. 시청자 반응이 얼마나 좋은지 보여줍니다.
- **matched_keywords**: 이 영상이 걸린 검색 키워드들.

## API 사용량

- 키워드 1개당 50개 검색 = 100 유닛 → 기본 실행 시 약 **810 유닛**
- 하루 10,000 유닛이므로 기본 설정으로 하루 약 12번 실행 가능

## 참고

- 검색 결과에는 AI로 만들지 않은 영상도 섞여 있을 수 있으니 상위 영상은 직접 확인하세요.
- `config/google_api_keys.json` 파일(API 키)은 다른 사람과 공유하거나 깃허브에 올리지 마세요.
