-- Test agent for Жалыбин Максим: constructor workflow + custom KPI metrics.

INSERT INTO platform_core.agent_cards (
    agent_id, title, version, description, department,
    tasks_json, kpi_metrics_json, interaction_mode
) VALUES (
    'test-agent-zhalybin-maxim-v1',
    'ИИ-агент: Жалыбин Максим (тест)',
    '1.0',
    'Тестовый агент конструктора для Жалыбина Максима. Извлекает процесс из регламента, сопоставляет роли и публикует карточку агента с KPI.',
    '',
    '[
      {
        "task_id": "parse_regulation",
        "title": "Извлечение процесса из регламента",
        "description": "Разобрать PDF/DOCX регламента на шаги, роли и контрольные точки",
        "evaluation_criteria": {"requires_steps": true, "requires_roles": true},
        "kpi_tags": ["accuracy", "completeness"]
      },
      {
        "task_id": "match_roles",
        "title": "Сопоставление ролей с ERP",
        "description": "Связать роли из регламента с должностями и подразделениями 1С",
        "evaluation_criteria": {"requires_erp_mapping": true},
        "kpi_tags": ["accuracy"]
      },
      {
        "task_id": "finalize_agent",
        "title": "Финализация карточки агента",
        "description": "Собрать черновик агента, KPI и задачи для публикации на платформе",
        "evaluation_criteria": {"requires_kpi_metrics": true, "requires_tasks": true},
        "kpi_tags": ["timeliness", "operator_keep"]
      }
    ]',
    '[
      {"metric_id": "task_success_rate", "title": "Доля успешно собранных агентов", "kind": "rate", "source": "agent_task_reports", "threshold_min": 0.88, "weight": 1.2},
      {"metric_id": "avg_quality_score", "title": "Качество извлечения процесса из регламента", "kind": "score", "source": "agent_task_reports", "threshold_min": 0.82, "weight": 1.5, "task_ids": ["parse_regulation"]},
      {"metric_id": "operator_keep_rate", "title": "Черновики без правок оператора", "kind": "rate", "source": "review_events", "threshold_min": 0.8, "weight": 2.0, "task_ids": ["finalize_agent"]},
      {"metric_id": "run_success_rate", "title": "Успешность прогонов конструктора", "kind": "rate", "source": "agent_runs", "threshold_min": 0.9, "weight": 1.0}
    ]',
    'pull'
) ON CONFLICT (agent_id) DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    tasks_json = EXCLUDED.tasks_json,
    kpi_metrics_json = EXCLUDED.kpi_metrics_json,
    updated_at = NOW();

-- Sample task reports so KPI summary shows non-zero values for this agent.
DELETE FROM kpi.agent_task_reports
WHERE agent_id = 'test-agent-zhalybin-maxim-v1';

INSERT INTO kpi.agent_task_reports (
    id, agent_id, task_id, status, quality_score, summary, outcome_json, metadata_json, created_at
) VALUES
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'parse_regulation', 'success', 0.91, 'Извлечено 12 шагов и 4 роли', '{"steps": 12, "roles": 4}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '6 days'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'match_roles', 'success', 0.87, 'Сопоставлено 4 из 4 ролей', '{"mapped": 4, "total": 4}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '6 days'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'finalize_agent', 'success', 0.93, 'Карточка опубликована', '{"status": "ready"}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '6 days'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'parse_regulation', 'success', 0.89, 'Извлечено 9 шагов и 3 роли', '{"steps": 9, "roles": 3}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '5 days'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'match_roles', 'success', 0.85, 'Сопоставлено 3 из 3 ролей', '{"mapped": 3, "total": 3}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '5 days'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'finalize_agent', 'success', 0.90, 'Черновик готов к ревью', '{"status": "review"}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '5 days'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'parse_regulation', 'success', 0.94, 'Полный процесс извлечён', '{"steps": 15, "roles": 5}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '4 days'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'match_roles', 'error', 0.62, 'Не найдена роль «Куратор проекта»', '{"mapped": 4, "total": 5}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '4 days'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'parse_regulation', 'success', 0.88, 'Извлечено 11 шагов', '{"steps": 11, "roles": 4}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '3 days'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'match_roles', 'success', 0.86, 'Сопоставлено 4 из 4 ролей', '{"mapped": 4, "total": 4}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '3 days'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'finalize_agent', 'success', 0.92, 'KPI метрики сохранены', '{"metrics": 4}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '3 days'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'parse_regulation', 'success', 0.90, 'Регламент МТО разобран', '{"steps": 10, "roles": 3}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '2 days'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'match_roles', 'success', 0.84, 'ERP mapping завершён', '{"mapped": 3, "total": 3}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '2 days'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'finalize_agent', 'success', 0.91, 'Агент готов к деплою', '{"status": "ready"}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '2 days'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'parse_regulation', 'success', 0.92, 'Новый регламент обработан', '{"steps": 8, "roles": 2}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '1 day'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'match_roles', 'success', 0.88, '2 роли сопоставлены', '{"mapped": 2, "total": 2}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '1 day'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'finalize_agent', 'error', 0.71, 'Не хватает KPI метрик', '{"status": "draft"}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '1 day'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'parse_regulation', 'success', 0.93, 'Последний регламент разобран', '{"steps": 14, "roles": 4}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '6 hours'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'match_roles', 'success', 0.89, '4 роли сопоставлены', '{"mapped": 4, "total": 4}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '5 hours'),
    (gen_random_uuid(), 'test-agent-zhalybin-maxim-v1', 'finalize_agent', 'success', 0.95, 'Тестовый агент опубликован', '{"status": "ready"}', '{"owner_fio": "Жалыбин Максим"}', NOW() - INTERVAL '4 hours');
