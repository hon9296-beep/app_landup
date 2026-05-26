package com.landup.user;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * 부팅 시 환경변수 (DEMO_USER_EMAIL / DEMO_USER_PASSWORD) 박혀있으면 시연용 계정 1개 자동 생성.
 *
 * 동작:
 *  - 환경변수 둘 다 비어있으면 skip (로컬/prod 어디서도 작동 X)
 *  - 해당 이메일 user 이미 있으면 skip (멱등 — 재기동/재배포에도 중복 생성 X)
 *  - 없으면 INSERT: isVerified=true, isAdmin=false, membership=basic
 *  - 비번은 BCrypt 해시 (AuthService 와 동일 인코더)
 *
 * 시연 후 .env 에서 DEMO_USER_* 줄 제거하면 다음 부팅 시 INSERT 안 됨. 이미 생성된 계정은 그대로.
 */
@Component
public class DemoUserSeeder implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(DemoUserSeeder.class);

    private final UserRepository userRepository;
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

    @Value("${demo.user.email:}")
    private String demoEmail;

    @Value("${demo.user.password:}")
    private String demoPassword;

    @Value("${demo.user.name:Demo User}")
    private String demoName;

    public DemoUserSeeder(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    @Override
    @Transactional
    public void run(ApplicationArguments args) {
        if (demoEmail == null || demoEmail.isBlank() || demoPassword == null || demoPassword.isBlank()) {
            log.info("[DemoUserSeeder] DEMO_USER_EMAIL/PASSWORD 미설정 — seed skip");
            return;
        }

        if (userRepository.findByEmail(demoEmail).isPresent()) {
            log.info("[DemoUserSeeder] 이미 존재 — skip (email={})", demoEmail);
            return;
        }

        User demo = User.builder()
                .name(demoName)
                .email(demoEmail)
                .password(passwordEncoder.encode(demoPassword))
                .membership(User.Membership.basic)
                .isAdmin(false)
                .isVerified(true)
                .build();

        userRepository.save(demo);
        log.info("[DemoUserSeeder] 시연 계정 생성 완료 — email={}", demoEmail);
    }
}
