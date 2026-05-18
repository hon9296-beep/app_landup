-- ══════════════════════════════════════════════════════════════════════════
-- LandUp DB init_v2.sql  — 완전 신규 설계
-- 생성: 2026-04-20, 갱신: 2026-04-21 (진규 small_pipeline_db_schema 흡수)
-- MySQL 8
-- 총 35 테이블
-- FK 의존성 순서로 CREATE TABLE 배열됨
--
-- ⚠️ 주의: 기존 db/init.sql 은 구버전이므로 참고하지 말 것.
--    본 파일은 docs/docs-shin/matrix/DB/확정/ 의 설계 문서 기반으로 작성됨.
--
-- 진규 흡수 항목 (2026-04-21 추가):
--   - locked_object / token_usage (신규 카테고리)
--   - floor_zones / floor_main_artery (DB_floor)
--   - brand_object_specs + brand_manuals.pdf_sha256 (DB_files)
--   - placement_failed_objects (DB_placement)
--   - object_clearance / object_wall_attachment (DB_object, 칼럼에서 1:1 테이블로 분리)
-- ══════════════════════════════════════════════════════════════════════════

SET NAMES utf8mb4;

-- ═══════════════════════════════════════════════════════════════
-- LEVEL 0: 독립 테이블 (FK 의존성 없음)
-- ═══════════════════════════════════════════════════════════════

-- 1) users -------------------------------------------------------
CREATE TABLE users (
    id BIGINT           AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100)  NOT NULL,
    phone       VARCHAR(20)   NULL,
    email       VARCHAR(255)  NOT NULL UNIQUE,
    password    VARCHAR(255)  NULL,
    membership  ENUM('basic','premium','max') NOT NULL DEFAULT 'basic',
    is_admin    BOOLEAN       NOT NULL DEFAULT FALSE,
    is_verified BOOLEAN       NOT NULL DEFAULT FALSE,  -- 이메일 인증 완료 여부 (2026-04-23 신규)
    plan_started_at DATETIME  NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- 플랜 월별 리셋 기준일 (2026-04-29 신규)
    created_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2) object_palette (정본 — 카탈로그 + std 규격 flat) ---------------
-- wall_attachment / clearance 는 1:1 별도 테이블로 분리됨 (2026-04-21)
CREATE TABLE object_palette (
    id BIGINT         AUTO_INCREMENT PRIMARY KEY,
    code           VARCHAR(64) NOT NULL UNIQUE,
    name_ko        VARCHAR(100) NOT NULL,
    priority       INT         NOT NULL DEFAULT 50,
    front_edge     ENUM('width','depth') NOT NULL DEFAULT 'width',
    is_structural  BOOLEAN     NOT NULL DEFAULT FALSE,
    fixture_role   VARCHAR(32) NULL,
    width_std_mm   FLOAT       NOT NULL,
    depth_std_mm   FLOAT       NOT NULL,
    height_std_mm  FLOAT       NOT NULL,
    created_at     TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_fixture_role (fixture_role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3) area_types --------------------------------------------------
CREATE TABLE area_types (
    id BIGINT         AUTO_INCREMENT PRIMARY KEY,
    code            VARCHAR(50) NOT NULL UNIQUE,
    name_ko         VARCHAR(50) NOT NULL,
    target_objects  JSON        NOT NULL,
    position_hint   VARCHAR(50) NULL,
    description     TEXT        NULL,
    display_order   INT         NOT NULL DEFAULT 0,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4) brand_categories --------------------------------------------
CREATE TABLE brand_categories (
    id BIGINT         AUTO_INCREMENT PRIMARY KEY,
    code         VARCHAR(50) NOT NULL UNIQUE,
    name_ko      VARCHAR(50) NOT NULL,
    folder_name  VARCHAR(100) NOT NULL,
    is_active    BOOLEAN     NOT NULL DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5) brand_defaults (single-row) ---------------------------------
CREATE TABLE brand_defaults (
    id BIGINT   PRIMARY KEY CHECK (id = 1),
    clearspace_mm              INT   NOT NULL DEFAULT 900,
    logo_clearspace_mm         INT   NOT NULL DEFAULT 500,
    character_orientation      VARCHAR(20) NOT NULL DEFAULT '자유',
    main_corridor_min_mm       INT   NOT NULL DEFAULT 900,
    emergency_path_min_mm      INT   NOT NULL DEFAULT 1200,
    wall_clearance_mm          INT   NOT NULL DEFAULT 300,
    object_gap_mm              INT   NOT NULL DEFAULT 300,
    main_artery_half_buffer_mm INT   NOT NULL DEFAULT 600,
    corridor_half_buffer_mm    INT   NOT NULL DEFAULT 450,
    inner_wall_buffer_mm       INT   NOT NULL DEFAULT 150,
    default_height_mm          INT   NOT NULL DEFAULT 1500,
    max_density_ratio          FLOAT NOT NULL DEFAULT 0.25,
    max_fallback_rounds        INT   NOT NULL DEFAULT 3,
    -- Tier 1-1 clearance step-down 전역 상수 (진규 2026-04-21 패치)
    scaling_reference_area_mm2 BIGINT NOT NULL DEFAULT 99000000 COMMENT 'scaled_clearance 기준 면적(mm²). 30평=ratio 1.0',
    step_down_mm               INT   NOT NULL DEFAULT 200 COMMENT 'fallback Phase 5 step-down 단위(mm)',
    updated_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6) layer_keywords ----------------------------------------------
CREATE TABLE layer_keywords (
    id BIGINT          AUTO_INCREMENT PRIMARY KEY,
    category   ENUM('entrance','emergency','inaccessible','sprinkler','hydrant','panel') NOT NULL,
    keyword    VARCHAR(100) NOT NULL,
    is_active  BOOLEAN      NOT NULL DEFAULT TRUE,
    UNIQUE KEY uk_category_keyword (category, keyword),
    INDEX idx_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7) space_cap_rules (진규) --------------------------------------
CREATE TABLE space_cap_rules (
    id BIGINT         AUTO_INCREMENT PRIMARY KEY,
    scope        VARCHAR(32) NOT NULL,
    key_name     VARCHAR(64) NOT NULL,
    key_kind     ENUM('object_type','fixture_role') NOT NULL,
    cap_value    SMALLINT    NOT NULL,
    reason_note  TEXT        NULL,
    UNIQUE KEY uk_scope_key (scope, key_name),
    INDEX idx_scope_kind (scope, key_kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ═══════════════════════════════════════════════════════════════
-- LEVEL 1: users / object_palette 에 의존
-- ═══════════════════════════════════════════════════════════════

-- 8) refresh_tokens ---------------------------------------------
CREATE TABLE refresh_tokens (
    token       VARCHAR(36) PRIMARY KEY,
    user_id BIGINT         NOT NULL,
    expires_at  DATETIME    NOT NULL,
    created_at  TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 9) naver_oauth -------------------------------------------------
CREATE TABLE naver_oauth (
    id BIGINT          AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT          NOT NULL,
    naver_id            VARCHAR(100) NOT NULL UNIQUE,
    access_token        TEXT         NOT NULL,
    refresh_token       TEXT         NULL,
    token_type          VARCHAR(50)  DEFAULT 'bearer',
    expires_at          DATETIME     NULL,
    naver_email         VARCHAR(255) NULL,
    naver_nickname      VARCHAR(100) NULL,
    naver_profile_image VARCHAR(500) NULL,
    naver_mobile        VARCHAR(50)  NULL,
    raw_json            TEXT         NULL,
    created_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 10) google_oauth ----------------------------------------------
CREATE TABLE google_oauth (
    id BIGINT          AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT          NOT NULL,
    google_id            VARCHAR(100) NOT NULL UNIQUE,
    access_token         TEXT         NOT NULL,
    refresh_token        TEXT         NULL,
    token_type           VARCHAR(50)  DEFAULT 'bearer',
    expires_at           DATETIME     NULL,
    google_email         VARCHAR(255) NULL,
    google_name          VARCHAR(100) NULL,
    google_profile_image VARCHAR(500) NULL,
    raw_json             TEXT         NULL,
    created_at           TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 11) kakao_oauth -----------------------------------------------
CREATE TABLE kakao_oauth (
    id BIGINT          AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT          NOT NULL,
    kakao_id            BIGINT       NOT NULL UNIQUE,
    access_token        TEXT         NOT NULL,
    refresh_token       TEXT         NULL,
    token_type          VARCHAR(50)  DEFAULT 'bearer',
    expires_at          DATETIME     NULL,
    kakao_email         VARCHAR(255) NULL,
    kakao_nickname      VARCHAR(100) NULL,
    kakao_profile_image VARCHAR(500) NULL,
    raw_json            TEXT         NULL,
    created_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 12) object_ranges ---------------------------------------------
CREATE TABLE object_ranges (
    id BIGINT         AUTO_INCREMENT PRIMARY KEY,
    object_palette_id BIGINT         NOT NULL,
    brand_category    VARCHAR(50) NULL,
    width_min_mm      FLOAT       NOT NULL,
    width_max_mm      FLOAT       NOT NULL,
    depth_min_mm      FLOAT       NOT NULL,
    depth_max_mm      FLOAT       NOT NULL,
    height_min_mm     FLOAT       NOT NULL,
    height_max_mm     FLOAT       NOT NULL,
    UNIQUE KEY uk_palette_category (object_palette_id, brand_category),
    FOREIGN KEY (object_palette_id) REFERENCES object_palette(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 13) object_aliases --------------------------------------------
CREATE TABLE object_aliases (
    id BIGINT          AUTO_INCREMENT PRIMARY KEY,
    object_palette_id BIGINT          NOT NULL,
    alias             VARCHAR(100) NOT NULL UNIQUE,
    FOREIGN KEY (object_palette_id) REFERENCES object_palette(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 14) object_max_count ------------------------------------------
CREATE TABLE object_max_count (
    id BIGINT         AUTO_INCREMENT PRIMARY KEY,
    object_palette_id BIGINT         NOT NULL,
    brand_category    VARCHAR(50) NULL,
    max_count         SMALLINT    NOT NULL,
    UNIQUE KEY uk_palette_category (object_palette_id, brand_category),
    FOREIGN KEY (object_palette_id) REFERENCES object_palette(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 14-b) object_pair_rules (VMD_PAIR_RULES seed — small 프롬프트 + large merge/verify) --
CREATE TABLE object_pair_rules (
    id BIGINT         AUTO_INCREMENT PRIMARY KEY,
    object_a_code      VARCHAR(64) NOT NULL,
    object_b_code      VARCHAR(64) NOT NULL,                    -- '*' 와일드카드 허용
    relation           ENUM('join','adjacent','separate') NOT NULL,
    min_gap_mm         INT         NOT NULL DEFAULT 0,
    overlap_margin_mm  INT         NOT NULL DEFAULT 0,
    source             ENUM('vmd_default','manual') NOT NULL DEFAULT 'vmd_default',
    UNIQUE KEY uk_pair_rule (object_a_code, object_b_code, relation, source),
    INDEX idx_a_code (object_a_code),
    INDEX idx_source (source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 14-c) object_clearance (진규 fixture_directional_clearance — 1:1) --
CREATE TABLE object_clearance (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    object_palette_id BIGINT NOT NULL UNIQUE,
    front_mm          INT NOT NULL DEFAULT 0,
    back_mm           INT NOT NULL DEFAULT 0,
    -- 인체 안전 하한선 (step-down 시 max(computed, floor) 강제)
    front_floor_mm    INT NOT NULL DEFAULT 0 COMMENT '인체 안전 최소 front clearance (mm)',
    back_floor_mm     INT NOT NULL DEFAULT 0 COMMENT '인체 안전 최소 back clearance (mm). 일반 기물은 0, counter만 600',
    FOREIGN KEY (object_palette_id) REFERENCES object_palette(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 14-d) object_wall_attachment (진규 fixture_wall_attachment — 1:1) --
CREATE TABLE object_wall_attachment (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    object_palette_id BIGINT NOT NULL UNIQUE,
    attachment        ENUM('flush','near','free','either') NOT NULL,
    FOREIGN KEY (object_palette_id) REFERENCES object_palette(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 15) floor_archive (도면 원본 박물관 — 2026-04-27 rename: pdf → floor_archive) -----
--   brand_archive 와 패턴 일관 (원본 박물관 trail).
--   라이프사이클: 7일 retention cron 예정.
--   분석 결과는 floor_detections 에 별도 영구 보관.
CREATE TABLE floor_archive (
    id BIGINT          AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT          NOT NULL,
    original_filename VARCHAR(500) NOT NULL,
    stored_filename   VARCHAR(500) NOT NULL,
    s3_url            VARCHAR(500) NULL,                                        -- 2026-04-27 추가: 외부 노출용 URL (CloudFront / signed URL)
    s3_key            VARCHAR(500) NULL,                                        -- 2026-04-27 추가: S3 bucket 내부 key (이관/관리용)
    page_count        INT          NOT NULL DEFAULT 0,
    status            ENUM('processing','done','error') NOT NULL DEFAULT 'processing',
    pages_json        MEDIUMTEXT   NULL,
    error_message     TEXT         NULL,
    created_at        TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_status (user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 16) brand 자산 그룹 — 원본/분석 분리 (2026-04-27 박물관 모델 적용) ───────────────────
-- 16-a) brand_archive (원본 박물관, 7일 retention)
--   목적: 사용자가 업로드한 매뉴얼 원본 PDF 보관. 시각적 미리보기 용
--   라이프사이클: created_at < NOW() - 7d → cron 자동 삭제
--   프로젝트와 무관 (FK 없음, user_id 만)
CREATE TABLE brand_archive (
    id                BIGINT       AUTO_INCREMENT PRIMARY KEY,
    user_id           BIGINT       NOT NULL,
    original_filename VARCHAR(500) NOT NULL,
    stored_filename   VARCHAR(500) NOT NULL,
    s3_url            VARCHAR(500) NULL,                                        -- 2026-04-27 추가: 외부 노출용 URL (CloudFront / signed URL)
    s3_key            VARCHAR(500) NULL,                                        -- 2026-04-27 추가: S3 bucket 내부 key (이관/관리용)
    pdf_sha256        VARCHAR(64)  NULL,                                        -- 디버깅/통계용 (UNIQUE X)
    file_size_bytes   INT          NULL,
    created_at        TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_created (user_id, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 16-b) brand_manuals (분석 결과 전용, 영구 자산)
--   목적: 브랜드 매뉴얼 LLM 분석 결과 (brand_data_json) 영구 보관
--   라이프사이클: 참조 0 + 30일 cron (활성 user_project 참조 중이면 영구)
--   원본 추적: brand_archive_id (FK SET NULL — 박물관 7일 후 NULL)
CREATE TABLE brand_manuals (
    id BIGINT          AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT          NOT NULL,
    brand_archive_id  BIGINT       NULL,                                        -- 원본 박물관 추적 (7일 후 NULL)
    page_count        INT          NOT NULL DEFAULT 0,
    status            ENUM('processing','done','error') NOT NULL DEFAULT 'processing',
    brand_data_json   MEDIUMTEXT   NULL,
    character_orientation VARCHAR(20) NULL COMMENT 'LLM 추출값. NULL 이면 brand_defaults.character_orientation 으로 fallback',
    error_message     TEXT         NULL,
    created_at        TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (brand_archive_id) REFERENCES brand_archive(id) ON DELETE SET NULL,
    INDEX idx_user_status (user_id, status),
    INDEX idx_archive (brand_archive_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 16-c) brand_object_specs (진규 brand_placement_rule 흡수 — 이름 변경) --
CREATE TABLE brand_object_specs (
    id BIGINT         AUTO_INCREMENT PRIMARY KEY,
    brand_manual_id BIGINT         NOT NULL,
    seq                  SMALLINT    NOT NULL,
    object_type          VARCHAR(64) NOT NULL,
    name                 VARCHAR(128) NULL,
    width_mm             INT         NULL,
    depth_mm             INT         NULL,
    height_mm            INT         NULL,
    preferred_zone       ENUM('entrance_zone','mid_zone','deep_zone') NULL,
    wall_attachment      ENUM('flush','near','free','either') NULL,
    front_clearance_mm   INT         NULL,
    back_clearance_mm    INT         NULL,
    required_direction   VARCHAR(64) NULL,
    preferred_wall       VARCHAR(64) NULL,
    min_count            SMALLINT    NULL,
    max_count            SMALLINT    NULL,
    max_count_source     ENUM('manual','inferred') NULL,
    material             TEXT        NULL,
    front_edge           ENUM('width','depth') NULL,
    UNIQUE KEY uk_manual_seq (brand_manual_id, seq),
    FOREIGN KEY (brand_manual_id) REFERENCES brand_manuals(id) ON DELETE CASCADE,
    INDEX idx_manual (brand_manual_id),
    INDEX idx_type (object_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ═══════════════════════════════════════════════════════════════
-- LEVEL 2: pdf / brand_manuals 에 의존
-- ═══════════════════════════════════════════════════════════════

-- 17) floor_detections (2026-04-27: pdf_id → floor_archive_id rename)
CREATE TABLE floor_detections (
    id BIGINT         AUTO_INCREMENT PRIMARY KEY,
    floor_archive_id BIGINT NULL,                              -- 2026-04-27 rename: pdf_id → floor_archive_id (박물관 7일 cron SET NULL 허용)
    page_number        INT         NOT NULL,
    brand_manual_id BIGINT         NULL,
    status             ENUM('processing','done','error') NOT NULL DEFAULT 'processing',
    scale_mm_per_px    FLOAT       NULL,
    scale_confirmed    BOOLEAN     NOT NULL DEFAULT FALSE,
    detected_width_mm  FLOAT       NULL,
    detected_height_mm FLOAT       NULL,
    ceiling_height_mm  FLOAT       NULL,
    usable_area_sqm    FLOAT       NULL,
    scale_type         ENUM('large','small','outdoor') NOT NULL,
    venue_type         ENUM('street_complex','street_standalone') NULL,
    usable_poly_json   MEDIUMTEXT  NULL,
    created_at         TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (floor_archive_id) REFERENCES floor_archive(id) ON DELETE SET NULL,  -- 박물관 7일 cron 시 NULL 처리 (분석 결과 영구)
    FOREIGN KEY (brand_manual_id) REFERENCES brand_manuals(id) ON DELETE SET NULL,
    INDEX idx_floor_archive_page (floor_archive_id, page_number),
    INDEX idx_scale_status (scale_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ═══════════════════════════════════════════════════════════════
-- LEVEL 3: floor_detections 에 의존
-- ═══════════════════════════════════════════════════════════════

-- 18) floor_points ----------------------------------------------
CREATE TABLE floor_points (
    id BIGINT   AUTO_INCREMENT PRIMARY KEY,
    floor_detection_id BIGINT   NOT NULL,
    type               ENUM('main_door','emergency_exit','sprinkler','fire_hydrant','electrical_panel') NOT NULL,
    x_mm               FLOAT NOT NULL,
    y_mm               FLOAT NOT NULL,
    width_mm           FLOAT NULL,
    is_main            BOOLEAN NULL,
    FOREIGN KEY (floor_detection_id) REFERENCES floor_detections(id) ON DELETE CASCADE,
    INDEX idx_floor_type (floor_detection_id, type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 19) floor_polygons --------------------------------------------
CREATE TABLE floor_polygons (
    id BIGINT          AUTO_INCREMENT PRIMARY KEY,
    floor_detection_id BIGINT          NOT NULL,
    kind               ENUM('inaccessible','dead_zone') NOT NULL,
    source             VARCHAR(30)  NOT NULL,
    polygon_json       MEDIUMTEXT   NOT NULL,
    center_x_mm        FLOAT        NULL,
    center_y_mm        FLOAT        NULL,
    radius_mm          FLOAT        NULL,
    FOREIGN KEY (floor_detection_id) REFERENCES floor_detections(id) ON DELETE CASCADE,
    INDEX idx_floor_kind (floor_detection_id, kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 19-b) concept_areas (concept_area.py LLM 결정 영역, 2026-05-09 init_v2.sql sync) -----
-- 운영 DB 에는 이미 존재 (Java ConceptArea Entity 가 의존). init_v2.sql 에만 누락이었음.
-- floor_anchors / placement_objects 가 FK 로 참조하므로 그들보다 먼저 정의.
CREATE TABLE concept_areas (
    id BIGINT          AUTO_INCREMENT PRIMARY KEY,
    floor_detection_id BIGINT          NOT NULL,
    name               VARCHAR(50)     NOT NULL,    -- 영문 키 (welcome/photo/experience/screening/retail/checkout/hybrid/lounge)
    polygon_json       TEXT            NULL,
    area_ratio         FLOAT           NULL,
    target_objects_json JSON           NULL,
    created_at         TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_concept_floor_detection (floor_detection_id),
    INDEX idx_concept_name (name),
    FOREIGN KEY (floor_detection_id) REFERENCES floor_detections(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 20) floor_anchors ---------------------------------------------
CREATE TABLE floor_anchors (
    id BIGINT          AUTO_INCREMENT PRIMARY KEY,
    floor_detection_id BIGINT          NOT NULL,
    scale              ENUM('large','small','outdoor') NOT NULL,
    anchor_key         VARCHAR(100) NOT NULL,
    x_mm               FLOAT        NOT NULL,
    y_mm               FLOAT        NOT NULL,
    wall_normal        ENUM('N','S','E','W','NE','NW','SE','SW','none') NULL,
    wall_angle_deg     FLOAT        NULL,
    wall_length_mm     FLOAT        NULL,
    label              VARCHAR(50)  NULL,
    zone_label         ENUM('entrance_zone','mid_zone','deep_zone') NULL,
    walk_mm            FLOAT        NULL,
    shelf_capacity     INT          NULL,
    concept_area_id    BIGINT       NULL,    -- 2026-05-09 추가 (Phase 2 concept_areas FK, init_v2.sql sync)
    UNIQUE KEY uk_floor_anchor (floor_detection_id, anchor_key),
    FOREIGN KEY (floor_detection_id) REFERENCES floor_detections(id) ON DELETE CASCADE,
    FOREIGN KEY (concept_area_id) REFERENCES concept_areas(id) ON DELETE SET NULL,
    INDEX idx_floor_scale (floor_detection_id, scale),
    INDEX idx_concept_area (concept_area_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 20-b) floor_zones (진규 zone_polygon — entrance/mid/deep 구역) --
CREATE TABLE floor_zones (
    id BIGINT        AUTO_INCREMENT PRIMARY KEY,
    floor_detection_id BIGINT        NOT NULL,
    zone_label         ENUM('entrance_zone','mid_zone','deep_zone') NOT NULL,
    polygon_json       MEDIUMTEXT NOT NULL,
    UNIQUE KEY uk_floor_zone (floor_detection_id, zone_label),
    FOREIGN KEY (floor_detection_id) REFERENCES floor_detections(id) ON DELETE CASCADE,
    INDEX idx_floor (floor_detection_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 20-c) floor_main_artery (진규 main_artery — 1:1) ---------------
CREATE TABLE floor_main_artery (
    id BIGINT        AUTO_INCREMENT PRIMARY KEY,
    floor_detection_id BIGINT        NOT NULL UNIQUE,
    linestring_json    MEDIUMTEXT NOT NULL,
    length_mm          FLOAT      NOT NULL,
    FOREIGN KEY (floor_detection_id) REFERENCES floor_detections(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 21) placement_results -----------------------------------------
CREATE TABLE placement_results (
    id BIGINT        AUTO_INCREMENT PRIMARY KEY,
    floor_detection_id BIGINT        NOT NULL,
    status              ENUM('processing','done','error') NOT NULL DEFAULT 'processing',
    density_ratio       FLOAT      NULL,
    user_requirements   TEXT       NULL,
    placed_count        INT        NOT NULL DEFAULT 0,
    failed_count        INT        NOT NULL DEFAULT 0,
    fallback_round      INT        NOT NULL DEFAULT 0,
    verification_passed BOOLEAN    NULL,
    ref_quality_score   FLOAT      NULL,
    report_text         TEXT       NULL,
    report_json         MEDIUMTEXT NULL,
    glb_path            VARCHAR(500) NULL,
    sub_path_json       TEXT         NULL,
    main_artery_json    TEXT         NULL,
    created_at          TIMESTAMP  DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (floor_detection_id) REFERENCES floor_detections(id) ON DELETE CASCADE,
    INDEX idx_floor (floor_detection_id),
    INDEX idx_status_created (status, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ═══════════════════════════════════════════════════════════════
-- LEVEL 4: placement_results 에 의존
-- ═══════════════════════════════════════════════════════════════

-- 22) placement_objects -----------------------------------------
CREATE TABLE placement_objects (
    id BIGINT         AUTO_INCREMENT PRIMARY KEY,
    placement_result_id BIGINT         NOT NULL,
    object_type         VARCHAR(64) NOT NULL,
    label               VARCHAR(100) NULL,    -- 2026-05-10 복원 (Python 한국어 라벨, 프론트 표시용)
    floor_anchor_id BIGINT         NULL,
    center_x_mm         FLOAT       NOT NULL,
    center_y_mm         FLOAT       NOT NULL,
    rotation_deg        FLOAT       NOT NULL DEFAULT 0,
    width_mm            FLOAT       NOT NULL,
    depth_mm            FLOAT       NOT NULL,
    height_mm           FLOAT       NOT NULL,
    zone_label          ENUM('entrance_zone','mid_zone','deep_zone') NULL,
    direction           ENUM('wall_facing','center','inward','focal','outward','freestanding') NULL,
    alignment           ENUM('parallel','perpendicular','none','opposite') NULL,
    wall_attachment     ENUM('flush','near','free','either') NULL,
    category            VARCHAR(50) NULL,
    concept_area_id     BIGINT      NULL,    -- 2026-05-09 추가 (Phase 2 concept_areas FK, init_v2.sql sync)
    graphic_face        VARCHAR(16) NULL,    -- 2026-05-10 추가 (partition_reuse 흡수 표시 — none/inner/outer/both)
    graphic_face_basis  VARCHAR(32) NULL,    -- 2026-05-10 추가 (default_front / photo_wall_substitute)
    placed_because      TEXT        NULL,
    created_at          TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (placement_result_id) REFERENCES placement_results(id) ON DELETE CASCADE,
    FOREIGN KEY (floor_anchor_id) REFERENCES floor_anchors(id) ON DELETE SET NULL,
    FOREIGN KEY (concept_area_id) REFERENCES concept_areas(id) ON DELETE SET NULL,
    INDEX idx_result (placement_result_id),
    INDEX idx_anchor (floor_anchor_id),
    INDEX idx_concept_area (concept_area_id),
    INDEX idx_type (object_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 23) placement_verifications -----------------------------------
CREATE TABLE placement_verifications (
    id BIGINT  AUTO_INCREMENT PRIMARY KEY,
    placement_result_id BIGINT  NOT NULL,
    placement_object_id BIGINT  NULL,
    rule                ENUM('floor_exit','dead_zone','main_artery','pair_separate','corridor','wall_clearance','emergency_exit') NOT NULL,
    severity            ENUM('blocking','warning') NOT NULL,
    detail              TEXT NULL,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (placement_result_id) REFERENCES placement_results(id) ON DELETE CASCADE,
    FOREIGN KEY (placement_object_id) REFERENCES placement_objects(id) ON DELETE CASCADE,
    INDEX idx_result_severity (placement_result_id, severity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 24) placement_cap_logs (진규) ---------------------------------
CREATE TABLE placement_cap_logs (
    id BIGINT          AUTO_INCREMENT PRIMARY KEY,
    placement_result_id BIGINT          NOT NULL,
    object_type         VARCHAR(64)  NOT NULL,
    dimension           VARCHAR(96)  NOT NULL,
    from_count          INT          NOT NULL,
    to_count            INT          NOT NULL,
    reason              TEXT         NOT NULL,
    created_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (placement_result_id) REFERENCES placement_results(id) ON DELETE CASCADE,
    INDEX idx_result (placement_result_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 24-b) placement_failed_objects (진규 failed_object) ------------
CREATE TABLE placement_failed_objects (
    id BIGINT          AUTO_INCREMENT PRIMARY KEY,
    placement_result_id BIGINT          NOT NULL,
    object_type         VARCHAR(64)  NOT NULL,
    reason              TEXT         NOT NULL,
    created_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (placement_result_id) REFERENCES placement_results(id) ON DELETE CASCADE,
    INDEX idx_result (placement_result_id),
    INDEX idx_type (object_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 24-c) token_usage (진규 — LLM 비용 집계) -----------------------
CREATE TABLE token_usage (
    id BIGINT          AUTO_INCREMENT PRIMARY KEY,
    placement_result_id BIGINT          NOT NULL,
    node_name           VARCHAR(64)  NOT NULL,
    input_tokens        INT          NOT NULL DEFAULT 0,
    output_tokens       INT          NOT NULL DEFAULT 0,
    cache_read_tokens   INT          NOT NULL DEFAULT 0,
    cache_write_tokens  INT          NOT NULL DEFAULT 0,
    model               VARCHAR(64)  NULL,
    called_at           TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_result_node (placement_result_id, node_name),
    FOREIGN KEY (placement_result_id) REFERENCES placement_results(id) ON DELETE CASCADE,
    INDEX idx_result (placement_result_id),
    INDEX idx_model_time (model, called_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ═══════════════════════════════════════════════════════════════
-- LEVEL 5: 다수 상위 테이블 참조
-- ═══════════════════════════════════════════════════════════════

-- 25) user_projects ---------------------------------------------
CREATE TABLE user_projects (
    id BIGINT          AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT          NOT NULL,
    name                VARCHAR(200) NULL,
    floor_archive_id BIGINT NULL,                              -- 2026-04-27 rename: pdf_id → floor_archive_id
    brand_manual_id BIGINT          NULL,
    floor_detection_id BIGINT          NULL,
    placement_result_id BIGINT          NULL,
    status              ENUM('processing','done','error') NOT NULL DEFAULT 'processing',
    deleted_at          DATETIME     NULL DEFAULT NULL,        -- soft delete 시각 (2026-04-29 신규)
    was_done            BOOLEAN      NOT NULL DEFAULT FALSE,   -- 삭제 전 완료 여부 (2026-04-29 신규)
    created_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (floor_archive_id) REFERENCES floor_archive(id) ON DELETE SET NULL,
    FOREIGN KEY (brand_manual_id) REFERENCES brand_manuals(id) ON DELETE SET NULL,
    FOREIGN KEY (floor_detection_id) REFERENCES floor_detections(id) ON DELETE SET NULL,
    FOREIGN KEY (placement_result_id) REFERENCES placement_results(id) ON DELETE SET NULL,
    INDEX idx_user_status (user_id, status),
    INDEX idx_user_created (user_id, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 25-b) locked_object (진규 — 사용자가 잠근 기물) ---------------
CREATE TABLE locked_object (
    id BIGINT         AUTO_INCREMENT PRIMARY KEY,
    user_project_id BIGINT         NOT NULL,
    object_type     VARCHAR(64) NOT NULL,
    center_x_mm     FLOAT       NOT NULL,
    center_y_mm     FLOAT       NOT NULL,
    width_mm        FLOAT       NOT NULL,
    depth_mm        FLOAT       NOT NULL,
    height_mm       FLOAT       NOT NULL,
    rotation_deg    FLOAT       NOT NULL DEFAULT 0,
    locked_at       TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_project_id) REFERENCES user_projects(id) ON DELETE CASCADE,
    INDEX idx_project (user_project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 26) jobs ------------------------------------------------------
CREATE TABLE jobs (
    id BIGINT          AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT          NOT NULL,
    job_type          ENUM('detect','brand','space_data','place','export') NOT NULL,
    status            ENUM('pending','running','done','error') NOT NULL DEFAULT 'pending',
    progress_stage    VARCHAR(50)  NULL,
    progress_pct      INT          NOT NULL DEFAULT 0,
    progress_message  VARCHAR(255) NULL,
    result_project_id BIGINT          NULL,
    error_message     TEXT         NULL,
    created_at        TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    started_at        TIMESTAMP    NULL,
    completed_at      TIMESTAMP    NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (result_project_id) REFERENCES user_projects(id) ON DELETE SET NULL,
    INDEX idx_user_status (user_id, status),
    INDEX idx_user_created (user_id, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 27) ref_image (관리자 레퍼런스 이미지 관리용) ------------------
-- 2026-04-23 신규 — 관리자 페이지 "레퍼런스 이미지 관리" 기능 백본.
-- 각 사용자 배치 사이클에서 참조한 ref 이미지를 프로젝트별로 기록.
-- 관리자가 FE 에서 악질 이미지 삭제 시 soft delete + 블랙리스트 등록.
-- S3 를 production 저장소로 사용 (s3_url). 로컬 파일은 dev/cache 용.
-- FK 정책:
--   user_project_id  ON DELETE SET NULL  — 프로젝트 삭제돼도 관리자 자산으로 이미지 보존
--   brand_category_id ON DELETE RESTRICT — 카테고리 삭제 전 ref_image 정리 강제
--   deleted_by / blacklisted_by ON DELETE SET NULL — 관리자 계정 삭제 시 이력 유지
-- UNIQUE (user_project_id, image_sha256) — 동일 프로젝트 내 중복 방지, 재등록은 UPDATE
CREATE TABLE ref_image (
    id                BIGINT       AUTO_INCREMENT PRIMARY KEY,
    user_project_id   BIGINT       NULL,
    brand_category_id BIGINT       NOT NULL,
    image_sha256      CHAR(64)     NOT NULL,
    floor_size_tier   ENUM('small','medium','large','outdoor') NOT NULL,
    search_keyword    VARCHAR(255) NULL,
    search_engine     ENUM('ddg','pinterest','tavily','manual') NULL,            -- 2026-04-26 추가: 어느 검색 엔진에서 가져왔는지
    source_url        VARCHAR(500) NULL,
    s3_url            VARCHAR(500) NULL,                                          -- 외부 노출용 URL (CloudFront / signed URL)
    file_path         VARCHAR(500) NULL,                                          -- 로컬/도커 파일 경로 (개발 환경 캐시)
    file_size_bytes   INT          NULL,
    ref_path          VARCHAR(500) NULL,                                          -- S3 bucket 내부 key (이관/관리용 — 예: references/캐릭터IP/포토존/ref_xxx.jpg)
    quality_score     DECIMAL(3,2) NULL,                                          -- 2026-04-26 추가: 0.00~1.00, Vision 분석 점수 (이미지_품질_필터 결과)
    is_deleted        BOOLEAN      NOT NULL DEFAULT FALSE,
    is_blacklisted    BOOLEAN      NOT NULL DEFAULT FALSE,
    used_count        INT          NOT NULL DEFAULT 0,                            -- 2026-04-26 추가: 디자인 채택 횟수 (사용자_선호_학습)
    rejected_count    INT          NOT NULL DEFAULT 0,                            -- 2026-04-26 추가: admin/사용자 거부 횟수
    deleted_at        TIMESTAMP    NULL,
    deleted_by        BIGINT       NULL,
    blacklisted_at    TIMESTAMP    NULL,
    blacklisted_by    BIGINT       NULL,
    created_at        TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_project_id)   REFERENCES user_projects(id)    ON DELETE SET NULL,
    FOREIGN KEY (brand_category_id) REFERENCES brand_categories(id) ON DELETE RESTRICT,
    FOREIGN KEY (deleted_by)        REFERENCES users(id)            ON DELETE SET NULL,
    FOREIGN KEY (blacklisted_by)    REFERENCES users(id)            ON DELETE SET NULL,
    UNIQUE KEY uq_project_sha (user_project_id, image_sha256),
    INDEX idx_category_tier (brand_category_id, floor_size_tier),
    INDEX idx_sha256_black (image_sha256, is_blacklisted),
    INDEX idx_created (created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 28) verification_tokens (이메일 인증 1회용 토큰) ------------------
-- 2026-04-23 신규 — 소셜 로그인(카카오/네이버/구글) 시 이메일 인증 링크 발송용.
-- 흐름: 가입/로그인 시점에 token(64자 랜덤) 발급 → 이메일로 링크 전송 →
--       유저가 /auth/verify?token=xxx 클릭 → verified_at 기록 + users.is_verified=TRUE.
-- user_id 타입 주의: Java Entity 가 columnDefinition="INT" 로 지정 (users.id 는 BIGINT 라
--   타입 불일치 이슈, 추후 BIGINT 로 정정 필요). FK 제약은 걸지 않음 (Entity 에서도 미설정).
CREATE TABLE verification_tokens (
    id          BIGINT       AUTO_INCREMENT PRIMARY KEY,
    user_id     INT          NOT NULL,
    token       VARCHAR(64)  NOT NULL UNIQUE,
    expires_at  DATETIME(6)  NOT NULL,
    created_at  DATETIME(6)  NULL,
    verified_at DATETIME(6)  NULL,
    INDEX idx_user (user_id),
    INDEX idx_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 29) payments (결제 내역) -----------------------------------------
-- heeyoung 담당. 토스페이먼츠 결제 흐름 (멤버십 구독/결제/취소).
-- 2026-04-22 heeyoung 가 RDS 에 수동 생성, 2026-04-23 init_v2.sql 반영.
-- Entity: backend/java/src/main/java/com/landup/payment/Payment.java (heeyoung 추가)
-- status: pending → success | failed | cancelled (이력 보존, 물리 삭제 X)
-- user_id / payment_method_id FK 는 Entity 레벨 @ManyToOne 없이 값만 저장 (명시적 제약 없음)
CREATE TABLE payments (
    id                 BIGINT       AUTO_INCREMENT PRIMARY KEY,
    user_id            BIGINT       NOT NULL,
    amount             INT          NOT NULL,
    plan_key           VARCHAR(20)  NULL,
    status             ENUM('pending','success','failed','cancelled') NOT NULL,
    method             VARCHAR(50)  NULL,
    order_id           VARCHAR(100) NOT NULL,
    payment_key        VARCHAR(200) NULL,
    payment_method_id  BIGINT       NULL,
    description        VARCHAR(200) NULL,
    next_billing_date  DATETIME(6)  NULL,
    cancelled_at       DATETIME(6)  NULL,
    type               VARCHAR(20)  NOT NULL DEFAULT 'SUBSCRIPTION',  -- SUBSCRIPTION / CREDIT (2026-04-29 신규)
    created_at         DATETIME(6)  NOT NULL,
    UNIQUE KEY uk_payments_order (order_id),
    INDEX idx_payments_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 39) cross_sections (단면도 업로드 이력) ------------------------------
-- yeonhwa 담당. 단면도 파일에서 천장 높이(ceiling_height_mm) 추출 이력 저장.
-- floor_detection_id: 연결된 평면도 분석 ID (단독 업로드 시 NULL 허용)
CREATE TABLE cross_sections (
    id                 BIGINT       AUTO_INCREMENT PRIMARY KEY,
    user_id            BIGINT       NOT NULL,
    floor_detection_id BIGINT       NULL,
    original_filename  VARCHAR(500) NOT NULL,
    stored_filename    VARCHAR(500) NOT NULL,
    file_type          VARCHAR(10)  NOT NULL DEFAULT 'pdf' COMMENT 'pdf, dxf, dwg',
    status             ENUM('processing','done','error') NOT NULL DEFAULT 'processing',
    section_ceiling_mm FLOAT        NULL,
    confidence         FLOAT        NULL,
    error_message      TEXT         NULL,
    created_at         TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (floor_detection_id) REFERENCES floor_detections(id) ON DELETE SET NULL,
    INDEX idx_user (user_id),
    INDEX idx_floor_detection (floor_detection_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 40) ref_image_analyses (레퍼런스 이미지 Vision 분석 결과 영구 보관) ---
-- 2026-04-29 신규 — ref_image (원본) 의 LLM 분석 결과 영속화.
-- 분리 이유: ref_image 는 기존 admin 페이지/검색/파일 관리 통합. 분석 JSON 은 별도 테이블에서 영구 보관.
-- 사용 시점: Python ref_image_analyzer 의 Vision 분석 결과 INSERT (캐시 hit 시 재사용).
-- 매칭 카테고리:
--   concept_area (large 영문 키 — welcome/photo/experience/screening/retail/checkout/hybrid/lounge)
--                 ↔ 한국어 라벨 매핑은 nodes_large/concept_area.py 의 CONCEPT_AREA_LABEL_KO
--   brand_category (보조 — 뷰티/음식/패션 등 기존 brand_categories 와 정합)
-- model_version: Vision 모델 변경 시 mismatch → 재분석 invalidation 트리거.
-- FK SET NULL: ref_image 삭제돼도 분석 결과 영구 유지 (LLM 디자인 활용은 JSON 만으로 가능).
-- 결정 근거: docs/docs-shin/main_tasks/TR_I_인프라/2026-04-29_[S3_레퍼런스_인프라]_분석결과_DB_캐시.md
CREATE TABLE ref_image_analyses (
    id                   BIGINT       AUTO_INCREMENT PRIMARY KEY,
    ref_image_id         BIGINT       NULL,
    concept_area         VARCHAR(50)  NULL,                                          -- 영문 키 (welcome/photo/experience/screening/retail/checkout/hybrid/lounge)
    brand_category       VARCHAR(50)  NULL,                                          -- 보조 (뷰티/음식 등)
    vision_analysis_json MEDIUMTEXT   NULL,                                          -- 8축 분석 결과 (layout_patterns/partition_usage/focal_points/...)
    model_version        VARCHAR(50)  NULL,                                          -- Vision 모델 버전 (mismatch 시 재분석)
    status               ENUM('processing','done','error') NOT NULL DEFAULT 'processing',
    error_message        TEXT         NULL,
    created_at           TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ref_image_id) REFERENCES ref_image(id) ON DELETE SET NULL,
    INDEX idx_area          (concept_area),
    INDEX idx_brand         (brand_category),
    INDEX idx_ref_image     (ref_image_id),
    INDEX idx_model_version (model_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ═══════════════════════════════════════════════════════════════
-- 플랜 제한 및 크레딧 관련 테이블 (2026-04-29 신규)
-- ═══════════════════════════════════════════════════════════════

-- 41) redeployment_logs — 재배치 LLM 호출 이력 (월별 횟수 계산)
CREATE TABLE redeployment_logs (
    id         BIGINT   AUTO_INCREMENT PRIMARY KEY,
    user_id    BIGINT   NOT NULL,
    project_id BIGINT   NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id)    REFERENCES users(id)         ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES user_projects(id) ON DELETE CASCADE,
    INDEX idx_rl_user    (user_id),
    INDEX idx_rl_project (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 42) user_credits — 유저별 크레딧 잔액
CREATE TABLE user_credits (
    id         BIGINT   AUTO_INCREMENT PRIMARY KEY,
    user_id    BIGINT   NOT NULL UNIQUE,
    balance    INT      NOT NULL DEFAULT 0,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 43) credit_transactions — 크레딧 구매·사용 이력
-- amount: 양수=충전, 음수=사용
-- type: PURCHASE / USE_REDEPLOY / USE_PROJECT
CREATE TABLE credit_transactions (
    id         BIGINT      AUTO_INCREMENT PRIMARY KEY,
    user_id    BIGINT      NOT NULL,
    amount     INT         NOT NULL,
    type       VARCHAR(30) NOT NULL,
    project_id BIGINT      NULL,
    created_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id)    REFERENCES users(id)         ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES user_projects(id) ON DELETE SET NULL,
    INDEX idx_ct_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ══════════════════════════════════════════════════════════════════════════
-- End of init_v2.sql  (43 tables)
-- 다음 단계: seed.py 로 OBJECT_STANDARDS / VMD_BOUNDARIES / VMD_PAIR_RULES /
--          VMD_WALL_ATTACHMENT / DIRECTIONAL_CLEARANCE / _SPACE_CAP_RULES_SMALL 등 소스 상수 삽입
-- ══════════════════════════════════════════════════════════════════════════
