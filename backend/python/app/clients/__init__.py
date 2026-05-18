"""Java 백엔드 및 외부 서비스 호출 클라이언트 모음.

Python 배치 엔진이 상위 레이어 (Java API / 외부 서비스) 를 호출할 때 사용.
HTTP 클라이언트는 httpx 기반. 실패 시 graceful degrade (파이프라인 blocking 금지).
"""
