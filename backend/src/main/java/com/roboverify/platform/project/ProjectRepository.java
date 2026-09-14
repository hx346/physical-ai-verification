package com.roboverify.platform.project;

import com.roboverify.platform.common.api.ErrorCode;
import com.roboverify.platform.common.exception.BizException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.OffsetDateTime;
import java.util.List;

@Repository
public class ProjectRepository {

    private static final String COLS = "id, name, description, status, created_by, created_at, updated_at";

    private final JdbcTemplate jdbcTemplate;

    public ProjectRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public ProjectRow insert(String name, String description, String createdBy) {
        return jdbcTemplate.queryForObject(
                "INSERT INTO project (name, description, status, created_by) "
                        + "VALUES (?, ?, 'ACTIVE', ?) RETURNING " + COLS,
                ProjectRepository::mapRow, name, description, createdBy);
    }

    public ProjectRow findById(String id) {
        var rows = jdbcTemplate.query("SELECT " + COLS + " FROM project WHERE id = ?::uuid",
                ProjectRepository::mapRow, id);
        if (rows.isEmpty()) {
            throw new BizException(ErrorCode.PROJECT_NOT_FOUND);
        }
        return rows.getFirst();
    }

    public List<ProjectRow> findAll() {
        return jdbcTemplate.query("SELECT " + COLS + " FROM project ORDER BY created_at DESC",
                ProjectRepository::mapRow);
    }

    private static ProjectRow mapRow(ResultSet rs, int rowNum) throws SQLException {
        return new ProjectRow(
                rs.getString("id"),
                rs.getString("name"),
                rs.getString("description"),
                rs.getString("status"),
                rs.getString("created_by"),
                toOffset(rs.getTimestamp("created_at")),
                toOffset(rs.getTimestamp("updated_at")));
    }

    private static OffsetDateTime toOffset(Timestamp ts) {
        return ts == null ? null : ts.toInstant().atOffset(OffsetDateTime.now().getOffset());
    }
}
