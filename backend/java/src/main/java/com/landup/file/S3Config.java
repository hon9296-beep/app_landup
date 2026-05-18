package com.landup.file;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import software.amazon.awssdk.auth.credentials.AnonymousCredentialsProvider;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.AwsCredentialsProvider;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.S3Client;

/**
 * AWS S3 클라이언트 설정 — 2026-04-27 신설.
 *
 * 환경변수 (application.yml):
 *   - AWS_ACCESS_KEY_ID
 *   - AWS_SECRET_ACCESS_KEY
 *   - AWS_REGION (기본: ap-northeast-2)
 *
 * 키가 없으면 AnonymousCredentialsProvider 로 폴백 — 빈 생성은 성공,
 * 실제 S3 호출 시점에 인증 실패.
 */
@Configuration
public class S3Config {

    @Bean
    public S3Client s3Client(
            @Value("${aws.access-key-id:}") String accessKey,
            @Value("${aws.secret-access-key:}") String secretKey,
            @Value("${aws.region:ap-northeast-2}") String region
    ) {
        AwsCredentialsProvider creds = (accessKey.isBlank() || secretKey.isBlank())
                ? AnonymousCredentialsProvider.create()
                : StaticCredentialsProvider.create(AwsBasicCredentials.create(accessKey, secretKey));
        return S3Client.builder()
                .region(Region.of(region))
                .credentialsProvider(creds)
                .build();
    }

}
