package com.roboverify.platform.auth;

import cn.dev33.satoken.stp.StpUtil;
import com.roboverify.platform.auth.dto.LoginRequest;
import com.roboverify.platform.auth.dto.LoginResponse;
import com.roboverify.platform.common.api.ErrorCode;
import com.roboverify.platform.common.exception.BizException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 登录：校验 auth_user（PBKDF2），成功后 Sa-Token 发会话。
 * 会话当前存内存（单实例 M0），集群化时切 Redis。
 */
@Service
public class AuthService {

    private static final Logger log = LoggerFactory.getLogger(AuthService.class);

    private static final String SELECT_USER = "SELECT id, password_hash, role FROM auth_user WHERE username = ?";
    private static final long TOKEN_TTL_SECONDS = 86_400L;

    private final JdbcTemplate jdbcTemplate;

    public AuthService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public LoginResponse login(LoginRequest request) {
        List<UserRow> users = jdbcTemplate.query(SELECT_USER, (rs, i) ->
                new UserRow(rs.getString("id"), rs.getString("password_hash"), rs.getString("role")),
                request.username());
        if (users.size() != 1 || !PasswordHasher.verify(request.password(), users.getFirst().passwordHash())) {
            log.warn("login failed, username={}", request.username());
            throw new BizException(ErrorCode.USERNAME_OR_PASSWORD_ERROR);
        }
        UserRow user = users.getFirst();
        StpUtil.login(request.username());
        StpUtil.getTokenSession().set("role", user.role());
        StpUtil.getTokenSession().set("userId", user.id());
        String token = StpUtil.getTokenValue();
        jdbcTemplate.update("INSERT INTO auth_token (token, user_id, expires_at) VALUES (?, ?, now() + interval '1 second' * ?) "
                        + "ON CONFLICT (token) DO NOTHING",
                token, java.util.UUID.fromString(user.id()), TOKEN_TTL_SECONDS);
        return new LoginResponse(token, request.username(), user.role());
    }

    private record UserRow(String id, String passwordHash, String role) {
    }
}
