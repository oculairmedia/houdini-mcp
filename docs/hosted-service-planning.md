# Houdini MCP Hosted Service - Planning Document

## Executive Summary

**Goal**: List Houdini MCP on the Anthropic Connectors Directory and OpenAI Apps SDK marketplace, enabling users to control Houdini through Claude and ChatGPT without local MCP server setup.

**Current State**: Local MCP server using hrpyc to connect to Houdini running on the user's machine. Works well but requires technical setup.

**Vision**: A seamless hosted service where users install a simple Houdini plugin, authenticate once, and immediately gain access to AI-powered Houdini control through their preferred AI assistant.

---

## Market Research Findings

### Anthropic Connectors Directory

- **Submission Guide**: https://support.claude.com/en/articles/12922490-remote-mcp-server-submission-guide
- **OAuth authentication required** for user authorization
- **Directory URL**: https://claude.com/connectors
- **Requirements**:
  - HTTPS endpoint with valid SSL certificate
  - OAuth 2.0 implementation
  - MCP protocol compliance (HTTP+SSE transport)
  - Privacy policy and terms of service
  - Security review process

### OpenAI Apps SDK (October 2025)

- **Built on MCP standard** - same protocol, different marketplace
- **Submission Guidelines**: https://developers.openai.com/apps-sdk/app-submission-guidelines
- **No OpenAI API key required** for MCP-based apps
- **Requirements**:
  - Similar OAuth flow
  - App review process
  - Usage policy compliance

### Competitive Landscape

| Service | Approach | Pricing |
|---------|----------|---------|
| Figma MCP | Cloud-native (browser-based) | Free tier + paid |
| GitHub MCP | API-only (no local component) | Usage-based |
| Blender GPT | Plugin-based, no hosted option | One-time purchase |

**Opportunity**: No hosted Houdini AI integration exists. First-mover advantage in professional 3D/VFX AI tooling.

---

## Architecture Challenge

**The Core Problem**: Houdini runs on the user's local machine with a GUI, but hosted MCP servers need to reach it over the internet.

Unlike cloud-native tools (Figma, GitHub), Houdini is:
- Desktop software requiring local installation
- GPU-intensive for rendering
- Tied to local file systems for assets
- Licensed per-seat, not API-accessible

### Option A: User-Hosted Tunnel

```
User Machine                          Hosted Service
┌─────────────┐                      ┌─────────────────┐
│   Houdini   │◄──hrpyc──►│ Tunnel  │────────────────►│  MCP Server    │
│             │           │ Agent   │  (WebSocket)    │  (HTTP+SSE)    │
└─────────────┘           └─────────┘                 └─────────────────┘
```

**How it works**:
- User runs a lightweight tunnel agent alongside Houdini
- Agent establishes outbound WebSocket connection to our server
- Hosted MCP proxies commands through the tunnel

**Pros**:
- Works with any firewall (outbound connections only)
- User maintains control over access
- Minimal changes to existing hrpyc architecture

**Cons**:
- Requires user to run additional software
- Two components to install (plugin + tunnel agent)
- More failure points

### Option B: Reverse Proxy / Cloudflare Tunnel

```
User Machine                          Hosted Service
┌─────────────┐                      ┌─────────────────┐
│   Houdini   │◄──hrpyc──►│ hrpyc  │◄──cloudflared───│  MCP Server    │
│             │           │ server │   (tunnel)      │                │
└─────────────┘           └────────┘                 └─────────────────┘
```

**How it works**:
- User exposes hrpyc port via Cloudflare Tunnel, ngrok, or similar
- Our MCP server connects directly through the tunnel
- No custom networking code needed

**Pros**:
- Uses existing, battle-tested tunnel infrastructure
- Simple architecture
- Cloudflare provides DDoS protection

**Cons**:
- Security concerns (exposing local service)
- Complex user setup (Cloudflare account, tunnel config)
- Potential latency from double-hop
- Reliance on third-party tunnel service

### Option C: Houdini Plugin with Outbound Connection (Recommended)

```
User Machine                          Hosted Service
┌─────────────────────────────────┐  ┌─────────────────────────────────┐
│  ┌─────────┐    ┌─────────────┐ │  │  ┌──────────────┐               │
│  │ Houdini │◄──►│ MCP Plugin  │─┼──┼─►│ WS Gateway   │◄──►MCP Server │
│  │  (GUI)  │    │ (WS client) │ │  │  │              │               │
│  └─────────┘    └─────────────┘ │  │  └──────────────┘               │
└─────────────────────────────────┘  └─────────────────────────────────┘
```

**How it works**:
- Extend existing Houdini plugin to include WebSocket client
- Plugin initiates outbound connection to our WebSocket gateway
- All MCP commands flow over this established connection
- Single component to install

**Pros**:
- Best user experience - just install plugin and authenticate
- No ports to open, no firewall issues
- Single point of installation
- Can show connection status in Houdini UI
- Full control over protocol and security

**Cons**:
- More complex plugin development
- Session management complexity
- Need to handle reconnection gracefully

### Option D: Cloud-Hosted Houdini (Future)

```
┌─────────────────────────────────────────────────────────────┐
│                    Cloud Provider (AWS/GCP)                  │
│  ┌─────────────┐    ┌─────────────────┐    ┌─────────────┐ │
│  │   Houdini   │◄──►│   MCP Server    │◄──►│  Claude/    │ │
│  │  (headless) │    │   (co-located)  │    │  ChatGPT    │ │
│  └─────────────┘    └─────────────────┘    └─────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**How it works**:
- Partner with cloud GPU providers (AWS, Lambda Labs, etc.)
- Spin up Houdini instances on demand
- True SaaS model with no user installation

**Pros**:
- Ultimate user experience - no installation at all
- Can offer rendering as a service
- Scales with demand
- Works from any device

**Cons**:
- Expensive GPU instances ($1-5/hour)
- SideFX licensing complexity (render farms vs. interactive)
- Users can't access local files easily
- Latency for interactive work
- Complex session management

**Recommendation**: Start with Option C for launch, explore Option D for enterprise tier.

---

## Recommended Architecture (Option C - Outbound Plugin)

```
┌─────────────────────────────────────────────────────────────┐
│                    User's Machine                            │
│  ┌─────────────┐    hrpyc     ┌──────────────────────┐     │
│  │   Houdini   │◄────────────►│  Houdini MCP Plugin  │     │
│  │   (GUI)     │              │  (WebSocket client)  │     │
│  └─────────────┘              └──────────┬───────────┘     │
│                                          │ outbound WS      │
│                                          │ (wss://...)      │
└──────────────────────────────────────────┼─────────────────┘
                                           │
                                           ▼
┌──────────────────────────────────────────────────────────────┐
│                   Hosted Infrastructure                       │
│                                                              │
│  ┌────────────────┐     ┌─────────────────────────────┐    │
│  │  OAuth/Auth    │     │   WebSocket Gateway         │    │
│  │  (Auth0/Clerk) │     │   (session management)      │    │
│  └───────┬────────┘     └─────────────┬───────────────┘    │
│          │                            │                      │
│          ▼                            ▼                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Houdini MCP Server                      │   │
│  │         (HTTP+SSE for Claude/OpenAI)                 │   │
│  │                                                      │   │
│  │   Routes MCP tool calls to user's Houdini via WS    │   │
│  └─────────────────────────────────────────────────────┘   │
│                            │                                 │
│                            ▼                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Database (PostgreSQL)                   │   │
│  │   - User accounts                                    │   │
│  │   - Session tokens                                   │   │
│  │   - Usage metrics                                    │   │
│  │   - Plugin registration                              │   │
│  └─────────────────────────────────────────────────────┘   │
│                            │                                 │
│                            ▼                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Redis (Session State)                   │   │
│  │   - Active WebSocket sessions                        │   │
│  │   - Rate limiting counters                           │   │
│  │   - Pub/sub for scaling                              │   │
│  └─────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### Component Details

#### WebSocket Gateway
- Handles thousands of concurrent plugin connections
- Session management (map user ID to active connection)
- Heartbeat/ping-pong for connection health
- Graceful reconnection handling
- Rate limiting per user

#### MCP HTTP+SSE Server
- Implements MCP protocol for Claude/ChatGPT
- Receives tool calls via HTTP POST
- Streams responses via Server-Sent Events (SSE)
- OAuth2 token validation
- Routes calls to correct user's WebSocket

#### Message Flow
```
1. Claude sends: POST /mcp/tools/execute {tool: "create_node", params: {...}}
2. MCP Server validates OAuth token, identifies user
3. MCP Server looks up user's active WebSocket connection
4. MCP Server sends command over WebSocket to plugin
5. Plugin executes via hrpyc, gets result
6. Plugin sends result back over WebSocket
7. MCP Server streams result via SSE to Claude
```

---

## Authentication Flow

### Initial Setup (One-time)

```
┌──────────┐     ┌──────────────┐     ┌─────────────────┐
│   User   │     │  Web Portal  │     │  Houdini Plugin │
└────┬─────┘     └──────┬───────┘     └────────┬────────┘
     │                  │                      │
     │  1. Sign up      │                      │
     │─────────────────►│                      │
     │                  │                      │
     │  2. Generate     │                      │
     │     API Key      │                      │
     │◄─────────────────│                      │
     │                  │                      │
     │  3. Download plugin                     │
     │─────────────────────────────────────────►
     │                  │                      │
     │  4. Enter API key in plugin             │
     │─────────────────────────────────────────►
     │                  │                      │
     │                  │  5. Connect WebSocket│
     │                  │◄─────────────────────│
     │                  │                      │
     │  6. Plugin shows "Connected" status     │
     │◄────────────────────────────────────────│
```

### Per-Session OAuth (Claude/ChatGPT)

```
┌──────────┐     ┌─────────┐     ┌──────────────┐     ┌─────────────┐
│   User   │     │  Claude │     │  Web Portal  │     │  MCP Server │
└────┬─────┘     └────┬────┘     └──────┬───────┘     └──────┬──────┘
     │                │                 │                    │
     │  1. Select     │                 │                    │
     │  Houdini MCP   │                 │                    │
     │───────────────►│                 │                    │
     │                │                 │                    │
     │  2. OAuth redirect               │                    │
     │◄───────────────│                 │                    │
     │                │                 │                    │
     │  3. Authorize  │                 │                    │
     │───────────────────────────────►  │                    │
     │                │                 │                    │
     │  4. Redirect with auth code      │                    │
     │◄──────────────────────────────── │                    │
     │                │                 │                    │
     │                │  5. Exchange code for token          │
     │                │──────────────────────────────────────►
     │                │                 │                    │
     │  6. Ready to use Houdini tools   │                    │
     │◄───────────────│                 │                    │
```

---

## Required Components

### 1. Web Portal

**Purpose**: User account management, API keys, billing

**Features**:
- User registration/login (OAuth via Google, GitHub)
- API key generation and rotation
- Usage dashboard (calls, data transferred)
- Billing management (Stripe integration)
- Plugin download with personalized config
- Documentation and tutorials

**Tech Stack**:
- Next.js 14 (App Router)
- Tailwind CSS + shadcn/ui
- Auth0 or Clerk for authentication
- Stripe for billing
- PostgreSQL via Prisma

### 2. WebSocket Gateway

**Purpose**: Maintain persistent connections to user plugins

**Features**:
- WebSocket server (wss://)
- API key authentication on connect
- Session registry (user → connection mapping)
- Heartbeat/keepalive (30-second intervals)
- Auto-reconnection support
- Horizontal scaling via Redis pub/sub

**Tech Stack**:
- Python FastAPI + websockets
- Or: Node.js + ws/Socket.io
- Redis for session state
- Kubernetes for scaling

### 3. MCP HTTP+SSE Endpoint

**Purpose**: Interface with Claude/ChatGPT marketplaces

**Features**:
- HTTP POST for tool calls
- SSE for streaming responses
- OAuth2 token validation
- Request routing to user's WebSocket
- Timeout handling (30-second default)
- Error responses per MCP spec

**Tech Stack**:
- Python FastAPI (consistent with existing codebase)
- SSE via `sse-starlette`
- OAuth2 via `authlib`

### 4. Enhanced Houdini Plugin

**Purpose**: Bridge between Houdini and hosted service

**Features**:
- WebSocket client (outbound to our gateway)
- API key storage (secure local storage)
- Connection status UI in Houdini
- Auto-reconnect on disconnect
- Queue for commands during reconnection
- hrpyc integration (existing)

**Tech Stack**:
- Python (Houdini's embedded Python)
- `websockets` library
- PySide2 for UI (Houdini's Qt)

### 5. Database Schema

```sql
-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    stripe_customer_id VARCHAR(255)
);

-- API Keys
CREATE TABLE api_keys (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    key_hash VARCHAR(255) NOT NULL,  -- bcrypt hash
    key_prefix VARCHAR(8) NOT NULL,   -- for display: "hdn_abc1..."
    name VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    last_used_at TIMESTAMP,
    revoked_at TIMESTAMP
);

-- Sessions (active WebSocket connections)
CREATE TABLE sessions (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    api_key_id UUID REFERENCES api_keys(id),
    connected_at TIMESTAMP DEFAULT NOW(),
    last_heartbeat TIMESTAMP,
    houdini_version VARCHAR(50),
    plugin_version VARCHAR(50),
    ip_address INET
);

-- Usage metrics
CREATE TABLE usage (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    timestamp TIMESTAMP DEFAULT NOW(),
    tool_name VARCHAR(255),
    duration_ms INTEGER,
    success BOOLEAN,
    error_message TEXT
);

-- OAuth tokens (for Claude/ChatGPT)
CREATE TABLE oauth_tokens (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    provider VARCHAR(50),  -- 'anthropic', 'openai'
    access_token_hash VARCHAR(255),
    refresh_token_hash VARCHAR(255),
    expires_at TIMESTAMP,
    scopes TEXT[]
);
```

---

## Phase Plan

### Phase 1: Foundation (4-6 weeks)

**Goal**: Basic infrastructure and plugin connectivity

- [ ] **Infrastructure Setup**
  - Docker Compose for local development
  - Kubernetes manifests for production
  - PostgreSQL + Redis deployment
  - Domain and SSL certificates

- [ ] **WebSocket Gateway**
  - Basic WebSocket server
  - API key authentication
  - Session management
  - Heartbeat mechanism

- [ ] **Enhanced Houdini Plugin**
  - WebSocket client integration
  - API key configuration UI
  - Connection status indicator
  - Basic reconnection logic

- [ ] **Web Portal MVP**
  - User registration (email/password)
  - API key generation
  - Plugin download page

**Deliverable**: Plugin can connect to hosted gateway and maintain connection

### Phase 2: MCP Integration (3-4 weeks)

**Goal**: Full MCP protocol support and marketplace compatibility

- [ ] **HTTP+SSE MCP Transport**
  - Implement MCP server over HTTP
  - SSE streaming for responses
  - Tool call routing

- [ ] **OAuth2 Provider**
  - Authorization server implementation
  - Token generation and validation
  - Refresh token flow

- [ ] **Command Routing**
  - Route MCP calls to user's WebSocket
  - Handle timeouts and errors
  - Response streaming back to caller

- [ ] **Testing**
  - Integration tests with Claude API
  - Load testing WebSocket gateway
  - Error scenario testing

**Deliverable**: Working MCP server that Claude can connect to

### Phase 3: Marketplace Submission (2-3 weeks)

**Goal**: Meet requirements and submit to marketplaces

- [ ] **Documentation**
  - User guide for plugin installation
  - API documentation
  - Troubleshooting guide

- [ ] **Legal**
  - Privacy policy
  - Terms of service
  - Data processing agreement

- [ ] **Anthropic Submission**
  - Complete submission form
  - Security questionnaire
  - Demo video/screenshots

- [ ] **OpenAI Submission**
  - App SDK registration
  - Review process

**Deliverable**: Submitted to both marketplaces

### Phase 4: Polish & Launch (2-3 weeks)

**Goal**: Production-ready with monetization

- [ ] **Usage Analytics**
  - Detailed usage tracking
  - Admin dashboard
  - Alerting for issues

- [ ] **Billing Integration**
  - Stripe subscription setup
  - Usage-based billing
  - Invoice generation

- [ ] **Rate Limiting**
  - Per-user rate limits
  - Tier-based limits
  - Graceful degradation

- [ ] **Launch**
  - Marketing website
  - Launch announcement
  - Support channels

**Deliverable**: Public launch with paying customers

---

## Technical Decisions Needed

### 1. Hosting Provider

| Option | Pros | Cons | Cost Estimate |
|--------|------|------|---------------|
| **AWS** | Most features, reliable | Complex, expensive | $200-500/mo |
| **GCP** | Good K8s support | Less ecosystem | $150-400/mo |
| **DigitalOcean** | Simple, affordable | Less scaling | $50-150/mo |
| **Railway/Render** | Easiest deployment | Limited control | $50-200/mo |

**Recommendation**: Start with Railway for speed, migrate to AWS as scale demands.

### 2. Authentication Provider

| Option | Pros | Cons | Cost |
|--------|------|------|------|
| **Auth0** | Full-featured, OAuth | Expensive at scale | $23/mo + usage |
| **Clerk** | Modern DX, React-native | Newer, less proven | $25/mo + usage |
| **Supabase Auth** | Free tier, PostgreSQL | Less OAuth features | Free - $25/mo |
| **Custom** | Full control | Dev time, security risk | Dev cost |

**Recommendation**: Clerk for developer experience and OAuth support.

### 3. WebSocket Framework

| Option | Pros | Cons |
|--------|------|------|
| **FastAPI + websockets** | Python ecosystem, async | Less WS-specific features |
| **Socket.io (Node)** | Battle-tested, auto-reconnect | Different language |
| **Django Channels** | Full framework | Heavier weight |

**Recommendation**: FastAPI + websockets (consistent with existing Python codebase).

### 4. Billing Model

| Model | Pros | Cons |
|-------|------|------|
| **Usage-based** | Fair, scales with value | Unpredictable revenue |
| **Subscription** | Predictable revenue | May overpay/underpay |
| **Freemium** | Low barrier, growth | Need to convert free users |
| **Hybrid** | Best of both | Complex to explain |

**Recommendation**: Freemium with usage-based tiers:
- Free: 100 calls/month
- Pro ($19/mo): 5,000 calls/month
- Team ($49/mo): 25,000 calls/month
- Enterprise: Custom

### 5. Monitoring Stack

| Option | Pros | Cons | Cost |
|--------|------|------|------|
| **Datadog** | Full-featured | Expensive | $15/host/mo |
| **Grafana Cloud** | Great dashboards | Learning curve | Free - $50/mo |
| **Sentry + simple metrics** | Error tracking | Less monitoring | $26/mo |

**Recommendation**: Sentry for errors + Grafana Cloud for metrics.

---

## Open Questions

### 1. SideFX Licensing

**Question**: Can users run Houdini for commercial automated workflows triggered by AI?

**Research needed**:
- Review Houdini EULA for automation clauses
- Contact SideFX licensing department
- Understand if this differs from render farm licensing

**Impact**: Could require special licensing arrangement or partnership.

### 2. Latency Requirements

**Question**: Is round-trip through WebSocket acceptable for interactive use?

**Estimated latency breakdown**:
- Claude to MCP server: 50-100ms
- MCP server to WebSocket gateway: 1-5ms
- WebSocket to user's plugin: 50-200ms (depends on location)
- Plugin to Houdini (hrpyc): 10-50ms
- Return trip: Similar

**Total**: 200-500ms round-trip

**Mitigation**:
- Regional gateway servers
- Connection pooling
- Async operations where possible

### 3. Security Review

**Question**: Do we need penetration testing before public launch?

**Considerations**:
- Handling user OAuth tokens
- API keys for Houdini access
- Potential for arbitrary code execution via hrpyc

**Recommendation**: Yes, at minimum:
- Automated security scanning (Snyk, etc.)
- Third-party pentest before launch
- Bug bounty program post-launch

### 4. Pricing Model

**Question**: What pricing maximizes adoption while covering costs?

**Cost analysis needed**:
- Infrastructure cost per user
- Support cost per user
- Customer acquisition cost

**Competitive research**:
- Similar creative tool integrations
- MCP marketplace pricing norms

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| SideFX licensing issues | Medium | High | Early legal consultation |
| Low marketplace adoption | Medium | High | Marketing, partnerships |
| Security breach | Low | Critical | Security audit, monitoring |
| WebSocket scaling issues | Medium | Medium | Load testing, auto-scaling |
| Plugin compatibility issues | Medium | Medium | Version testing, gradual rollout |
| Competitor launches first | Low | Medium | Focus on quality, community |

---

## Success Metrics

### Launch Metrics (3 months)
- [ ] 500 registered users
- [ ] 100 monthly active users
- [ ] 10 paying customers
- [ ] < 1% error rate
- [ ] < 500ms average latency

### Growth Metrics (12 months)
- [ ] 5,000 registered users
- [ ] 1,000 monthly active users
- [ ] 100 paying customers
- [ ] $5,000 MRR

---

## Next Steps

### Immediate (This Week)
1. [ ] Validate architecture with proof-of-concept WebSocket connection
2. [ ] Research SideFX licensing terms (email licensing@sidefx.com)
3. [ ] Estimate hosting costs for different providers
4. [ ] Create GitHub project board for tracking

### Short-term (Next 2 Weeks)
1. [ ] Set up development environment (Docker Compose)
2. [ ] Prototype WebSocket gateway
3. [ ] Extend plugin with basic WebSocket client
4. [ ] Create detailed technical spec for Phase 1

### Medium-term (Next Month)
1. [ ] Complete Phase 1 development
2. [ ] Begin OAuth integration research
3. [ ] Draft privacy policy and ToS
4. [ ] Set up staging environment

---

## Appendix

### A. MCP Protocol Reference

The Model Context Protocol (MCP) defines how AI assistants communicate with external tools.

**Key endpoints**:
- `POST /mcp/initialize` - Establish session
- `POST /mcp/tools/list` - List available tools
- `POST /mcp/tools/call` - Execute a tool
- `GET /mcp/events` - SSE stream for responses

**Authentication**: OAuth 2.0 Bearer token in Authorization header.

### B. Houdini hrpyc Reference

hrpyc enables remote Python execution in Houdini.

**Current capabilities**:
- Node creation and manipulation
- Parameter access and modification
- Scene traversal
- Python expression evaluation

**Limitations**:
- Synchronous calls only
- No native async support
- Connection must be established before use

### C. Existing Codebase Structure

```
houdini-mcp/
├── src/
│   ├── houdini_mcp/
│   │   ├── server.py      # Current MCP server
│   │   ├── tools.py       # Tool implementations
│   │   └── hrpyc_client.py # Houdini connection
│   └── houdini_plugin/
│       └── python/        # Houdini shelf tools
├── docs/
├── tests/
└── docker-compose.yml
```

**Changes needed for hosted service**:
- New `hosted/` directory for gateway and portal
- Plugin enhancement for WebSocket
- Shared types/protocols between components
