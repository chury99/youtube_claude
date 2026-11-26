# 유튜브 자동 업로드 설정 (최초 1회)

업로더는 완성 영상을 **비공개**로 올립니다. 확인한 뒤 YouTube Studio에서 직접 공개로 바꾸면 됩니다.
조회용 API 키(`config/google_api_keys.json`)로는 업로드할 수 없어서, 채널 계정 로그인용 **OAuth 클라이언트**가 따로 필요합니다.

## 1. OAuth 동의 화면 만들기
1. https://console.cloud.google.com 에서 지금 API 키를 만든 프로젝트를 선택합니다.
2. **API 및 서비스 → 라이브러리**에서 `YouTube Data API v3`가 "사용" 상태인지 확인합니다.
3. **API 및 서비스 → OAuth 동의 화면**(Google 인증 플랫폼)으로 갑니다.
   - 앱 이름: 아무거나 (예: `my-shorts-uploader`), 지원 이메일: 본인 이메일
   - 대상(User type): **외부**
4. **대상** 메뉴에서 **테스트 사용자**에 영상을 올릴 채널의 Google 계정을 추가합니다.
5. 같은 화면에서 게시 상태를 **프로덕션으로 푸시**합니다.
   - "테스트" 상태로 두면 로그인 토큰이 **7일마다 만료**되어 다시 로그인해야 합니다.
   - 검증받지 않은 앱이라 로그인할 때 "Google에서 확인하지 않은 앱" 경고가 나옵니다. 본인이 만든 앱이니 **고급 → (앱 이름)(으)로 이동**을 눌러 진행하면 됩니다.

## 2. OAuth 클라이언트 만들기
1. **API 및 서비스 → 사용자 인증 정보 → + 사용자 인증 정보 만들기 → OAuth 클라이언트 ID**
2. 애플리케이션 유형: **데스크톱 앱**, 이름: 아무거나
3. 만든 뒤 **JSON 다운로드**를 누릅니다.
4. 받은 파일을 `config/youtube_oauth_client.json` 이름으로 옮깁니다.
   (형식 예시: `config/youtube_oauth_client.json.example`. 이 파일은 깃에 올라가지 않습니다.)

## 3. 채널 계정으로 로그인 (터미널에서 직접)
```bash
python3 scripts/youtube_upload.py --auth
```
브라우저가 열리면 영상을 올릴 채널 계정으로 로그인하고 "YouTube 동영상 관리" 권한을 허용합니다.
"인증 완료" 화면이 나오면 끝입니다. 토큰은 `config/youtube_token.json`에 저장됩니다 (깃 제외).

확인:
```bash
python3 scripts/youtube_upload.py --check
```

## 4. 꼭 알아 둘 점: 감사(audit) 전에는 "비공개 잠금"
2020년 7월 28일 이후 만든 API 프로젝트는 Google의 **감사를 통과하기 전까지 업로드한 영상이 비공개로 잠깁니다.**
잠긴 영상은 Studio에서도 공개로 바꿀 수 없을 수 있습니다.

- 감사 신청: Google의 "YouTube API Services - Audit and Quota Extension Form"
  (https://support.google.com/youtube/contact/yt_api_form)
  - 용도: 본인 채널에 직접 만든 영상을 올리는 개인용 업로드 도구라고 적습니다.
  - 심사에 며칠~몇 주가 걸릴 수 있습니다.
- 감사 전에도 업로드 자체는 되므로, 설정이 잘 됐는지 시험해 볼 수는 있습니다.
- 감사 전에 공개해야 하는 영상은 YouTube Studio에서 직접 업로드하세요. 업로드 정보는 `5_videos/shorts/<기본이름>/upload.json`과 기획안 [9]에 정리돼 있습니다.

## 업로드 한도
- 업로드는 하루 할당량 안에서 횟수 제한이 있습니다. 하루 쇼츠 몇 개 수준이면 충분합니다.
- 한도를 넘으면 "오늘 업로드 한도를 넘었습니다" 메시지가 나옵니다. 다음 날 다시 시도하세요.

## 직접 업로드할 때
```bash
python3 scripts/youtube_upload.py 5_videos/shorts/<기본이름>/<기본이름>.mp4 --meta 5_videos/shorts/<기본이름>/upload.json --dry-run
python3 scripts/youtube_upload.py 5_videos/shorts/<기본이름>/<기본이름>.mp4 --meta 5_videos/shorts/<기본이름>/upload.json
```
- 공개 상태는 `private`(기본), `unlisted`만 됩니다. 전체 공개는 Studio에서 직접 바꿉니다.
- 같은 영상을 두 번 올리지 않도록 `upload_result.json`이 있으면 멈춥니다. 다시 올리려면 `--force`.

## 채널 분석 권한 (분석가용)
로그인할 때 업로드 권한과 함께 **읽기 전용** 권한 두 개를 받습니다.
- `youtube.readonly`: 채널·영상 목록과 통계
- `yt-analytics.readonly`: 조회수, 시청 시간, 시청률, 유입 경로, 시청자 정보

예전에 업로드 권한만으로 로그인했다면 `python3 scripts/youtube_upload.py --auth`를 한 번 더 실행하세요.
`--check`에 "채널 분석 권한 있음"이 나오면 됩니다. 분석은 아래처럼 실행합니다.
```bash
python3 scripts/youtube_analytics.py --days 28
```
Google Cloud에서 **YouTube Analytics API**도 "사용"으로 켜 두어야 합니다 (API 및 서비스 → 라이브러리 → `YouTube Analytics API`).

## 재생목록 자동 정리 (롱폼·쇼츠 분리)
업로드가 끝나면 영상을 종류별 **공개 재생목록**에 자동으로 넣습니다(안의 비공개 영상은 공개로 바꾸기 전까지 남에게 보이지 않음).
- `5_videos/longform/…` → `Knitted Stories for Kids | Full Episodes` (롱폼·주간 모음집)
- `5_videos/shorts/…` → `Knitted Stories for Kids | Shorts`
- 재생목록이 없으면 처음 한 번 만들고 ID를 `config/youtube_playlists.json`에 저장합니다(깃에 올리지 않음). Studio에서 이름을 바꿔도 계속 같은 재생목록에 넣습니다.

필요한 권한은 `youtube.force-ssl`(재생목록 만들기·영상 넣기)입니다. 한 번만 설정하면 됩니다.
1. Google Cloud Console → **API 및 서비스 → OAuth 동의 화면 → 데이터 액세스(범위)** → 범위 추가에서 `https://www.googleapis.com/auth/youtube.force-ssl`을 추가하고 저장합니다.
2. 터미널에서 `python3 scripts/youtube_upload.py --auth`를 다시 실행하고, 채널 계정으로 로그인해 새 권한을 허용합니다.
3. `python3 scripts/youtube_upload.py --check`에 "재생목록 권한 있음"이 나오면 됩니다.
4. 이미 올린 영상을 한 번에 넣으려면: `python3 scripts/youtube_upload.py --playlist-sync` (빠진 영상만, 올린 순서대로)

권한이 없을 때는 업로드만 하고 재생목록은 건너뜁니다. 특정 영상만 빼려면 `--playlist none`, 다른 목록에 넣으려면 `--playlist longform|shorts`.
