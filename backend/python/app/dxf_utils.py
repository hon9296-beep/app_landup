"""DXF/DWG 공통 유틸리티 — nodes_small/parser_dxf, nodes_large/parser_dxf 공유."""
import logging
import os
import platform
import re
import subprocess
import tempfile
from collections import Counter

import ezdxf

logger = logging.getLogger(__name__)


def read_dxf_bytes(data: bytes):
    """DXF bytes → ezdxf Document."""
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".dxf")
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(data)
        return ezdxf.readfile(tmp_path)
    finally:
        os.unlink(tmp_path)


def convert_dwg_to_dxf(data: bytes) -> bytes:
    """DWG bytes → DXF bytes 변환 (ODA File Converter 사용).

    Windows: ODAFileConverter 직접 실행.
    Linux/Mac: xvfb-run 경유 (GUI 없는 서버 환경 대응).
    ODA File Converter 미설치 시 안내 메시지 포함 에러 발생.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        in_dir = os.path.join(tmp_dir, "in")
        out_dir = os.path.join(tmp_dir, "out")
        os.makedirs(in_dir)
        os.makedirs(out_dir)

        dwg_path = os.path.join(in_dir, "input.dwg")
        with open(dwg_path, "wb") as f:
            f.write(data)

        if platform.system() == "Windows":
            cmd = ["ODAFileConverter", in_dir, out_dir, "ACAD2018", "DXF", "0", "1"]
        else:
            cmd = ["xvfb-run", "-a", "ODAFileConverter", in_dir, out_dir, "ACAD2018", "DXF", "0", "1"]

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            if result.returncode != 0:
                raise ValueError("DWG 파일 변환에 실패했습니다. 파일이 손상되었거나 지원하지 않는 형식일 수 있습니다.")
        except FileNotFoundError:
            raise ValueError(
                "ODA File Converter가 설치되어 있지 않습니다. "
                "https://www.opendesign.com/guestfiles/oda_file_converter 에서 설치 후 다시 시도해주세요."
            )
        except subprocess.TimeoutExpired:
            raise ValueError("DWG 파일 처리 시간이 초과되었습니다. 파일 크기를 확인해주세요.")

        dxf_path = os.path.join(out_dir, "input.dxf")
        if not os.path.exists(dxf_path):
            raise ValueError("DWG 파일 변환에 실패했습니다. 파일이 손상되었거나 지원하지 않는 형식일 수 있습니다.")

        with open(dxf_path, "rb") as f:
            return f.read()


def extract_ceiling_height_from_dxf(data: bytes) -> dict:
    """단면도 DXF 파일에서 층고(2100~6000mm) 추출 — Model space 전체 스캔.

    단면도 파일은 파일 전체가 단면도이므로 레이아웃 분리 없이
    Model space의 모든 TEXT/MTEXT/DIMENSION 엔티티를 스캔.

    반환: {"ceiling_height_mm": float | None, "confidence": float}
      - confidence 기준:
          후보 없음          → 0.0
          후보 1개           → 0.5
          같은 값 2회 이상   → 0.8
          같은 값 3회 이상   → 0.9
          DIMENSION 엔티티 포함 시 → +0.1 (최대 1.0)
    """
    HEIGHT_PATTERN = re.compile(
        r'(?:H\s*=\s*)?(\d{1,2},\d{3}|\d{4})(?:\s*mm)?',
        re.IGNORECASE
    )
    doc = read_dxf_bytes(data)
    msp = doc.modelspace()
    candidates = []
    has_dimension = False

    for entity in msp.query("TEXT MTEXT"):
        try:
            text = entity.dxf.text if hasattr(entity.dxf, 'text') else entity.plain_mtext()
        except Exception:
            continue
        for m in HEIGHT_PATTERN.findall(text or ""):
            val = float(m.replace(",", ""))
            if 2100 <= val <= 6000:
                candidates.append(val)

    for entity in msp.query("DIMENSION"):
        val = getattr(entity.dxf, 'actual_measurement', None)
        if val and 2100 <= val <= 6000:
            candidates.append(float(round(val)))
            has_dimension = True

    if not candidates:
        logger.info("[dxf_utils] 단면도에서 층고 감지 실패 (후보 없음)")
        return {"ceiling_height_mm": None, "confidence": 0.0}

    most_common_val, most_common_count = Counter(candidates).most_common(1)[0]

    if most_common_count >= 3:
        confidence = 0.9
    elif most_common_count == 2:
        confidence = 0.8
    else:
        confidence = 0.5

    if has_dimension:
        confidence = min(1.0, confidence + 0.1)

    logger.info("[dxf_utils] 층고 감지: %smm confidence=%.1f (후보=%s)", most_common_val, confidence, candidates)
    return {"ceiling_height_mm": most_common_val, "confidence": confidence}
