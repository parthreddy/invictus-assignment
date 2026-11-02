-- Row-Level Security: tenant isolation enforced in the database, not the app.
--
-- Applied by scripts/init_db.py AFTER the tables are created (as the admin role).
-- The app connects as riverbend_app, which is NOT the table owner and NOT a
-- superuser, so these policies bind to it. The policy predicate compares each
-- row's shop_id to the per-transaction app.shop_id set by tenant_session().
--
-- current_setting('app.shop_id', true) returns NULL when unset; NULL = shop_id
-- is never true, so a session with no shop context sees zero rows. Safe default.

DO $$
DECLARE
    tbl text;
    tenant_tables text[] := ARRAY[
        'inbound_message', 'work_order', 'conversation',
        'outbox', 'spend_ledger', 'llm_call'
    ];
BEGIN
    FOREACH tbl IN ARRAY tenant_tables LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
        -- FORCE so the policy applies even if the table owner queries it.
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);

        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', tbl);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (shop_id = current_setting(''app.shop_id'', true)) '
            'WITH CHECK (shop_id = current_setting(''app.shop_id'', true))',
            tbl
        );

        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO riverbend_app', tbl
        );
    END LOOP;

    -- The shop table is global (needed to authenticate a key -> shop); read-only
    -- to the app role, no RLS.
    GRANT SELECT ON shop TO riverbend_app;

    -- Sequences for the serial PKs.
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO riverbend_app;
END $$;
