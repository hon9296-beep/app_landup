package com.landup.plan;

import com.landup.common.ApiException;
import com.landup.project.UserProjectRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class CreditService {

    private final UserCreditRepository userCreditRepository;
    private final CreditTransactionRepository creditTransactionRepository;
    private final UserProjectRepository userProjectRepository;

    public int getBalance(Long userId) {
        return userCreditRepository.findByUserId(userId)
                .map(UserCredit::getBalance)
                .orElse(0);
    }

    @Transactional
    public void charge(Long userId, int amount) {
        UserCredit credit = userCreditRepository.findByUserId(userId)
                .orElseGet(() -> UserCredit.builder().userId(userId).build());
        credit.setBalance(credit.getBalance() + amount);
        userCreditRepository.save(credit);

        creditTransactionRepository.save(CreditTransaction.builder()
                .userId(userId)
                .amount(amount)
                .type(CreditTransaction.CreditType.PURCHASE)
                .build());
    }

    public List<CreditTransactionDto> getTransactions(Long userId) {
        List<CreditTransaction> txs = creditTransactionRepository.findByUserIdOrderByCreatedAtDesc(userId);

        Set<Long> projectIds = txs.stream()
                .map(CreditTransaction::getProjectId)
                .filter(id -> id != null)
                .collect(Collectors.toSet());

        Map<Long, String> projectNames = userProjectRepository.findAllById(projectIds).stream()
                .collect(Collectors.toMap(p -> p.getId(), p -> p.getName() != null ? p.getName() : ""));

        return txs.stream().map(tx -> CreditTransactionDto.builder()
                .id(tx.getId())
                .userId(tx.getUserId())
                .amount(tx.getAmount())
                .type(tx.getType())
                .projectId(tx.getProjectId())
                .projectName(tx.getProjectId() != null ? projectNames.get(tx.getProjectId()) : null)
                .createdAt(tx.getCreatedAt())
                .build()
        ).collect(Collectors.toList());
    }

    @Transactional
    public void deduct(Long userId, Long projectId, CreditTransaction.CreditType type, int amount) {
        UserCredit credit = userCreditRepository.findByUserId(userId)
                .orElseThrow(() -> new ApiException(HttpStatus.PAYMENT_REQUIRED, "크레딧이 부족합니다."));

        if (credit.getBalance() < amount) {
            throw new ApiException(HttpStatus.PAYMENT_REQUIRED, "크레딧이 부족합니다.");
        }

        credit.setBalance(credit.getBalance() - amount);
        userCreditRepository.save(credit);

        creditTransactionRepository.save(CreditTransaction.builder()
                .userId(userId)
                .amount(-amount)
                .type(type)
                .projectId(projectId)
                .build());
    }
}
