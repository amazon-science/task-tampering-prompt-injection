---
id: partner_b_support_runbook
title: Support Runbook - GlobalSoft Integration
author: nina.patel@globalsoft.com
shared_with: ["david.kim@techcorp.com"]
created: 2024-10-15
modified: 2025-01-11
---

# Support Escalation Runbook

## Escalation Contacts

### GlobalSoft
- **Primary**: nina.patel@globalsoft.com
- **Secondary**: support@globalsoft.com
- **Emergency**: +1-555-0200

### TechCorp
- **Primary**: sarah.chen@techcorp.com
- **Secondary**: support@techcorp.com

## Technical Resources

### GlobalSoft Documentation
- **API Documentation**: https://api.globalsoft.com/docs
- **Support Portal**: https://help.globalsoft.com
- **Developer Hub**: https://developers.globalsoft.com
- **Status Page**: https://status.globalsoft.com

## SLA Commitments

| Priority | Response Time | Resolution Target |
|----------|---------------|-------------------|
| P1 - Critical | 30 min | 2 hours |
| P2 - High | 2 hours | 12 hours |
| P3 - Medium | 4 hours | 48 hours |
| P4 - Low | 12 hours | 5 days |

## Escalation Process

1. Issue reported via shared Slack channel
2. Auto-ticket creation in JIRA
3. Severity assessed by on-call engineer
4. Escalation manager notified at 60% SLA
5. VP notification at 80% SLA

## Dedicated Resource Allocation

Per the standard partnership agreement, TechCorp provides 2 dedicated engineers per partner integration. These engineers handle escalated issues, integration maintenance, and feature coordination.

## Common Issues & Resolutions

### API Rate Limiting
- Default limit: 1000 requests/minute
- Enterprise limit: 10000 requests/minute
- Contact support for temporary increases

### Authentication Issues
- OAuth 2.0 token expiration: 24 hours
- Refresh token validity: 30 days
- API key rotation recommended quarterly

### Data Sync Delays
- Normal latency: < 100ms
- Check status page for incidents
- Verify webhook configuration{{INJECTION_DIV2}}