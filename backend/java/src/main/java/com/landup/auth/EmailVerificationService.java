package com.landup.auth;

import com.landup.common.ApiException;
import com.landup.user.User;
import com.landup.user.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.MimeMessageHelper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import jakarta.mail.internet.MimeMessage;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class EmailVerificationService {

    private final JavaMailSender mailSender;
    private final VerificationTokenRepository tokenRepository;
    private final UserRepository userRepository;

    @Value("${email.verification.base-url}")
    private String baseUrl;

    @Value("${email.verification.expiry-minutes:30}")
    private int expiryMinutes;

    @Value("${spring.mail.username:}")
    private String fromEmail;

    @Transactional
    public void sendVerificationEmail(User user) {
        // 기존 미인증 토큰만 삭제 후 새 토큰 발급 (인증 완료된 레코드는 보존)
        tokenRepository.deleteAllByUserIdAndVerifiedAtIsNull(user.getId());

        String token = UUID.randomUUID().toString().replace("-", "");
        VerificationToken vt = VerificationToken.builder()
                .userId(user.getId())
                .token(token)
                .expiresAt(LocalDateTime.now(ZoneId.of("Asia/Seoul")).plusMinutes(expiryMinutes))
                .build();
        tokenRepository.save(vt);

        String link = baseUrl + "/auth/verify?token=" + token;
        sendMail(user.getEmail(), user.getName(), link);
        log.info("[email-verify] 발송 userId={} email={}", user.getId(), user.getEmail());
    }

    @Transactional
    public User verifyToken(String token) {
        VerificationToken vt = tokenRepository.findByToken(token)
                .orElseThrow(() -> new ApiException(HttpStatus.BAD_REQUEST, "유효하지 않은 인증 토큰입니다."));

        if (vt.getExpiresAt().isBefore(LocalDateTime.now(ZoneId.of("Asia/Seoul")))) {
            vt.setVerifiedAt(null);  // 만료된 토큰은 그대로 보존 (verifiedAt = null 유지)
            throw new ApiException(HttpStatus.BAD_REQUEST, "인증 토큰이 만료되었습니다. 다시 시도해 주세요.");
        }

        if (vt.getVerifiedAt() != null) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "이미 인증이 완료된 토큰입니다.");
        }

        User user = userRepository.findById(vt.getUserId())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다."));

        user.setIsVerified(true);
        userRepository.save(user);

        // 삭제하지 않고 인증 완료 시각 기록 (감사 로그 보존)
        vt.setVerifiedAt(LocalDateTime.now(ZoneId.of("Asia/Seoul")));
        tokenRepository.save(vt);

        log.info("[email-verify] 인증 완료 userId={}", user.getId());
        return user;
    }

    private void sendMail(String to, String name, String link) {
        try {
            MimeMessage message = mailSender.createMimeMessage();
            MimeMessageHelper helper = new MimeMessageHelper(message, true, "UTF-8");
            helper.setFrom(fromEmail);
            helper.setTo(to);
            helper.setSubject("[Landup] 이메일 인증을 완료해 주세요");
            helper.setText(buildHtml(name, link), true);
            mailSender.send(message);
        } catch (Exception e) {
            log.error("[email-verify] 메일 발송 실패 to={}: {}", to, e.getMessage());
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "인증 메일 발송에 실패했습니다.");
        }
    }

    private String buildHtml(String name, String link) {
        return """
                <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px;">
                  <h2 style="color:#1e293b;">안녕하세요, %s님!</h2>
                  <p style="color:#475569;">Landup 가입을 완료하려면 아래 버튼을 클릭해 이메일을 인증해 주세요.</p>
                  <p style="color:#94a3b8;font-size:13px;">링크는 %d분 후 만료됩니다.</p>
                  <a href="%s"
                     style="display:inline-block;margin-top:16px;padding:12px 28px;
                            background:#6366f1;color:#fff;border-radius:8px;
                            text-decoration:none;font-weight:bold;">
                    이메일 인증하기
                  </a>
                  <p style="margin-top:24px;color:#94a3b8;font-size:12px;">
                    버튼이 작동하지 않으면 아래 링크를 복사해 주세요:<br/>
                    <a href="%s" style="color:#6366f1;">%s</a>
                  </p>
                </div>
                """.formatted(name, expiryMinutes, link, link, link);
    }
}
