-- Phase 12 — Fortinet NSE4 topic taxonomy seed.
--
-- Idempotent: repeated runs are safe. Topics belong to ONE Fortinet
-- NSE4 exam; the script discovers it by code='NSE4' (case-insensitive)
-- and refuses if multiple matches exist.
--
-- Run via:
--   psql -h 127.0.0.1 -U exam_platform_user -d exam_platform_db \
--        -v ON_ERROR_STOP=1 -f content/topics-seed.sql
--
-- Manual review of the topic list is deliberate — admin should adjust
-- weights / descriptions in the UI rather than via SQL.

\set ON_ERROR_STOP on

DO $$
DECLARE
    v_exam_id BIGINT;
    v_count   INT;
BEGIN
    SELECT count(*), max(id)
    INTO   v_count, v_exam_id
    FROM   exams
    WHERE  upper(code) = 'NSE4'
      AND  deleted_at IS NULL;

    IF v_count = 0 THEN
        RAISE NOTICE 'no NSE4 exam yet — create one in /admin/exams first; topics not seeded';
        RETURN;
    ELSIF v_count > 1 THEN
        RAISE EXCEPTION 'ambiguous: % exams with code=NSE4 — resolve before seeding', v_count;
    END IF;

    -- Idempotent upsert keyed on (exam_id, slug).
    INSERT INTO topics (exam_id, name, slug, description, weight, created_at, updated_at)
    VALUES
      (v_exam_id, 'Firewall Policy',          'firewall-policy',          'IPv4/IPv6 firewall policies, sequence and matching, NAT integration.',          12.5, now(), now()),
      (v_exam_id, 'NAT',                      'nat',                      'SNAT, DNAT, central NAT, VIP, IP pools.',                                       10.0, now(), now()),
      (v_exam_id, 'VPN',                      'vpn',                      'IPsec site-to-site, IPsec remote access, SSL VPN, dial-up VPN.',                 15.0, now(), now()),
      (v_exam_id, 'Routing',                  'routing',                  'Static routes, policy routes, RIP/OSPF/BGP basics.',                             10.0, now(), now()),
      (v_exam_id, 'Security Profiles',        'security-profiles',        'Antivirus, web filter, application control, IPS, DLP, file filter.',             15.0, now(), now()),
      (v_exam_id, 'FortiGate Authentication', 'fortigate-authentication', 'Local auth, LDAP, RADIUS, FSSO, two-factor.',                                    10.0, now(), now()),
      (v_exam_id, 'Logging',                  'logging',                  'Local disk, syslog, FortiAnalyzer, log filter, log search.',                      8.0, now(), now()),
      (v_exam_id, 'High Availability',        'high-availability',        'A-A and A-P modes, session sync, failover.',                                     10.0, now(), now()),
      (v_exam_id, 'System Administration',    'system-administration',    'Admin profiles, FortiCloud, firmware, configuration backups.',                    9.5, now(), now())
    ON CONFLICT (exam_id, slug) DO UPDATE
      SET name        = EXCLUDED.name,
          description = EXCLUDED.description,
          weight      = EXCLUDED.weight,
          updated_at  = now();

    RAISE NOTICE 'NSE4 topics seeded into exam id %', v_exam_id;
END
$$;
