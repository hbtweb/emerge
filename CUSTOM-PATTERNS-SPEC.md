# Emerge Custom Patterns Specification

**Status**: Draft
**Author**: Claude + User
**Date**: 2025-12-17

---

## Overview

Enable project-specific dependency pattern recognition through configuration files, allowing Emerge to understand framework-specific patterns (WordPress hooks, Laravel facades, custom DI containers) without hardcoding framework knowledge.

---

## File Location

```
project-root/
├── .emerge/
│   ├── patterns.yaml      # Custom pattern definitions
│   ├── edges.yaml         # Edge connection rules (optional, can be in patterns.yaml)
│   └── file_types.yaml    # Custom file type definitions (optional)
└── src/
```

Emerge loads `.emerge/patterns.yaml` automatically when scanning a project.

---

## Pattern Definition Schema

### Basic Structure

```yaml
version: "1.0"

# Metadata
meta:
  name: "WordPress Plugin Patterns"
  description: "Patterns for WordPress hook system and common plugin patterns"
  frameworks: [wordpress, woocommerce]

# Node type definitions
node_types:
  hook:
    description: "WordPress action/filter hook"
    properties:
      - name: string
      - type: enum[action, filter]

  service:
    description: "DI container service"
    properties:
      - interface: string
      - implementation: string

# Pattern definitions
patterns:
  - id: wp_add_action
    name: "WordPress Add Action"
    # ... pattern details

# Edge rules
edges:
  - id: hook_triggers_listener
    # ... edge details
```

---

## Pattern Matching

### Pattern Properties

```yaml
patterns:
  - id: unique_identifier          # Required: unique ID for this pattern
    name: "Human Readable Name"    # Required: display name
    description: "What this finds" # Optional: documentation

    # Scope
    language: php                  # Language to apply to (or "any")
    file_pattern: "**/*.php"       # Glob pattern for files (optional)
    exclude: ["vendor/**"]         # Exclusion globs (optional)

    # Matching
    match:
      type: regex                  # regex | ast | semantic
      pattern: "..."               # The pattern itself
      flags: [multiline, ignorecase]  # Optional regex flags

    # Extraction
    captures:
      - name: hook_name
        group: 1
        transform: lowercase       # Optional: lowercase, trim, resolve_class
      - name: callback
        group: 2
        transform: resolve_class   # Resolve to FQCN if possible

    # What this creates in the graph
    creates:
      node:
        type: hook_listener        # Node type from node_types
        id: "$file:$line:$hook_name"  # Unique node ID template
        properties:
          hook: $hook_name
          callback: $callback
          file: $file
          line: $line
```

### Match Types

#### 1. Regex (Simple)

```yaml
match:
  type: regex
  pattern: "add_action\\(['\"]([^'\"]+)['\"],\\s*\\[\\s*\\$this\\s*,\\s*['\"]([^'\"]+)['\"]\\s*\\]"
  # Captures: (1) hook name, (2) method name
```

#### 2. Regex (Multiline)

```yaml
match:
  type: regex
  pattern: |
    add_action\(
      \s*['"]([^'"]+)['"],\s*  # hook name
      (.+?)                     # callback (lazy)
      (?:,\s*(\d+))?           # priority (optional)
      (?:,\s*(\d+))?           # accepted args (optional)
    \s*\)
  flags: [multiline, extended]
```

#### 3. AST Pattern (Future)

```yaml
match:
  type: ast
  pattern:
    type: function_call
    name: add_action
    arguments:
      - capture: hook_name
      - capture: callback
```

#### 4. Semantic Pattern (Future)

```yaml
match:
  type: semantic
  pattern: "call to add_action with string literal and callable"
```

---

## Capture Transforms

```yaml
captures:
  - name: class_name
    group: 1
    transform: resolve_class    # Resolve relative to current namespace/use statements

  - name: hook_name
    group: 2
    transform: lowercase        # Normalize to lowercase

  - name: method
    group: 3
    transform: trim             # Remove whitespace

  - name: fqcn
    group: 1
    transform:
      - trim
      - resolve_class           # Chain multiple transforms
```

### Available Transforms

| Transform | Description |
|-----------|-------------|
| `trim` | Remove leading/trailing whitespace |
| `lowercase` | Convert to lowercase |
| `uppercase` | Convert to uppercase |
| `resolve_class` | Resolve to FQCN using file's namespace/use statements |
| `strip_quotes` | Remove surrounding quotes |
| `normalize_path` | Convert path separators, resolve relative paths |
| `extract_class` | Extract class name from `[$obj, 'method']` pattern |
| `extract_method` | Extract method name from callable pattern |

---

## Node Creation

### Single Node

```yaml
creates:
  node:
    type: hook_listener
    id: "hook:$hook_name:$file:$line"
    label: "$hook_name listener"
    properties:
      hook: $hook_name
      callback: $callback
      priority: $priority
      file: $file
      line: $line
```

### Multiple Nodes

```yaml
creates:
  nodes:
    - type: hook
      id: "hook:$hook_name"
      singleton: true           # Only create one node per unique ID
      properties:
        name: $hook_name

    - type: hook_listener
      id: "listener:$file:$line"
      properties:
        hook: $hook_name
        callback: $callback
```

### Implicit Edge

```yaml
creates:
  node:
    type: hook_listener
    id: "listener:$file:$line"

  edge:
    from: $current_file         # Special variable: the file being parsed
    to: "hook:$hook_name"
    type: listens_to
    properties:
      priority: $priority
```

---

## Edge Rules

Edges connect patterns that were found separately.

```yaml
edges:
  # Connect do_action calls to add_action registrations
  - id: hook_triggers_listeners
    name: "Hook triggers listeners"

    from:
      pattern: wp_do_action     # Reference to pattern ID
      node_type: hook_trigger   # Or reference node type

    to:
      pattern: wp_add_action
      node_type: hook_listener

    match:
      # How to determine these nodes should connect
      type: property_equals
      properties: [hook_name]   # Match when hook_name property equals

    edge:
      type: triggers
      directed: true
      properties:
        async: false

  # Connect interface to implementation
  - id: di_binding
    from:
      node_type: interface_reference
    to:
      node_type: service_binding
    match:
      type: property_equals
      from_property: interface
      to_property: interface
    edge:
      type: implemented_by
```

### Match Types for Edges

```yaml
match:
  # Exact property match
  type: property_equals
  properties: [hook_name]

  # Property contains
  type: property_contains
  from_property: namespace
  to_property: class_fqcn

  # Regex match between properties
  type: property_regex
  from_property: pattern
  to_property: path

  # Custom expression
  type: expression
  expr: "from.namespace == to.namespace && from.class == to.class"
```

---

## Complete WordPress Example

```yaml
version: "1.0"

meta:
  name: "WordPress Patterns"
  frameworks: [wordpress]

node_types:
  hook:
    properties: [name, type]
  hook_listener:
    properties: [hook, callback, priority, file, line]
  hook_trigger:
    properties: [hook, file, line]
  shortcode:
    properties: [tag, callback, file, line]

patterns:
  # add_action('hook', callback, priority, args)
  - id: wp_add_action
    name: "Add Action"
    language: php
    match:
      type: regex
      pattern: "add_action\\s*\\(\\s*['\"]([^'\"]+)['\"]\\s*,\\s*(.+?)(?:\\s*,\\s*(\\d+))?(?:\\s*,\\s*(\\d+))?\\s*\\)"
    captures:
      - name: hook_name
        group: 1
      - name: callback
        group: 2
        transform: [trim, extract_class]
      - name: priority
        group: 3
        default: "10"
      - name: accepted_args
        group: 4
        default: "1"
    creates:
      nodes:
        - type: hook
          id: "action:$hook_name"
          singleton: true
          properties:
            name: $hook_name
            type: action
        - type: hook_listener
          id: "listener:$file:$line"
          properties:
            hook: $hook_name
            callback: $callback
            priority: $priority
      edge:
        from: "listener:$file:$line"
        to: "action:$hook_name"
        type: listens_to

  # add_filter('hook', callback, priority, args)
  - id: wp_add_filter
    name: "Add Filter"
    language: php
    match:
      type: regex
      pattern: "add_filter\\s*\\(\\s*['\"]([^'\"]+)['\"]\\s*,\\s*(.+?)(?:\\s*,\\s*(\\d+))?(?:\\s*,\\s*(\\d+))?\\s*\\)"
    captures:
      - name: hook_name
        group: 1
      - name: callback
        group: 2
        transform: [trim, extract_class]
      - name: priority
        group: 3
        default: "10"
      - name: accepted_args
        group: 4
        default: "1"
    creates:
      nodes:
        - type: hook
          id: "filter:$hook_name"
          singleton: true
          properties:
            name: $hook_name
            type: filter
        - type: hook_listener
          id: "listener:$file:$line"
          properties:
            hook: $hook_name
            callback: $callback
            priority: $priority
      edge:
        from: "listener:$file:$line"
        to: "filter:$hook_name"
        type: listens_to

  # do_action('hook', ...args)
  - id: wp_do_action
    name: "Do Action"
    language: php
    match:
      type: regex
      pattern: "do_action\\s*\\(\\s*['\"]([^'\"]+)['\"]"
    captures:
      - name: hook_name
        group: 1
    creates:
      node:
        type: hook_trigger
        id: "trigger:$file:$line"
        properties:
          hook: $hook_name
      edge:
        from: "trigger:$file:$line"
        to: "action:$hook_name"
        type: triggers

  # apply_filters('hook', value, ...args)
  - id: wp_apply_filters
    name: "Apply Filters"
    language: php
    match:
      type: regex
      pattern: "apply_filters\\s*\\(\\s*['\"]([^'\"]+)['\"]"
    captures:
      - name: hook_name
        group: 1
    creates:
      node:
        type: hook_trigger
        id: "trigger:$file:$line"
        properties:
          hook: $hook_name
      edge:
        from: "trigger:$file:$line"
        to: "filter:$hook_name"
        type: triggers

  # add_shortcode('tag', callback)
  - id: wp_shortcode
    name: "Shortcode"
    language: php
    match:
      type: regex
      pattern: "add_shortcode\\s*\\(\\s*['\"]([^'\"]+)['\"]\\s*,\\s*(.+?)\\s*\\)"
    captures:
      - name: tag
        group: 1
      - name: callback
        group: 2
        transform: extract_class
    creates:
      node:
        type: shortcode
        id: "shortcode:$tag"
        properties:
          tag: $tag
          callback: $callback

edges:
  # Connect triggers to listeners via the hook node
  - id: action_flow
    name: "Action triggers listeners"
    from:
      node_type: hook_trigger
    to:
      node_type: hook_listener
    match:
      type: property_equals
      properties: [hook]
    edge:
      type: may_trigger
      properties:
        indirect: true  # Via hook system, not direct call
```

---

## DI Container Example (Mesh)

```yaml
version: "1.0"

meta:
  name: "Mesh DI Patterns"
  frameworks: [mesh, wordpress]

patterns:
  # EDN service definition: {:class Mesh\\Services\\MyService}
  - id: edn_service
    name: "EDN Service Definition"
    language: edn
    file_pattern: "config/*.edn"
    match:
      type: regex
      pattern: ":class\\s+([\\w\\\\]+)"
    captures:
      - name: class_fqcn
        group: 1
    creates:
      node:
        type: service
        id: "service:$class_fqcn"
        properties:
          class: $class_fqcn
          config_file: $file

  # EDN route handler: {:handler Mesh\\Controllers\\MyController}
  - id: edn_route_handler
    name: "EDN Route Handler"
    language: edn
    file_pattern: "config/routes.edn"
    match:
      type: regex
      pattern: ":handler\\s+([\\w\\\\]+)"
    captures:
      - name: controller
        group: 1
    creates:
      node:
        type: route_handler
        id: "handler:$controller"
        properties:
          controller: $controller

  # PHP container get: $container->get(ServiceInterface::class)
  - id: container_get
    name: "Container Get"
    language: php
    match:
      type: regex
      pattern: "->get\\(([\\w\\\\]+)::class\\)"
    captures:
      - name: interface
        group: 1
        transform: resolve_class
    creates:
      edge:
        from: $current_file
        to: "service:$interface"
        type: depends_on
```

---

## Laravel Example

```yaml
version: "1.0"

meta:
  name: "Laravel Patterns"
  frameworks: [laravel]

patterns:
  # Facade usage: Cache::get()
  - id: facade_usage
    name: "Facade Call"
    language: php
    match:
      type: regex
      pattern: "\\b(App|Cache|Config|DB|Event|Log|Queue|Route|Storage|View)\\s*::"
    captures:
      - name: facade
        group: 1
    creates:
      edge:
        from: $current_file
        to: "facade:$facade"
        type: uses_facade

  # Event dispatch: Event::dispatch(new MyEvent())
  - id: event_dispatch
    name: "Event Dispatch"
    language: php
    match:
      type: regex
      pattern: "Event::dispatch\\(new\\s+([\\w\\\\]+)"
    captures:
      - name: event_class
        group: 1
        transform: resolve_class
    creates:
      node:
        type: event_dispatch
        id: "dispatch:$file:$line"
        properties:
          event: $event_class
      edge:
        from: $current_file
        to: "event:$event_class"
        type: dispatches

  # Event listener in EventServiceProvider
  - id: event_listener
    name: "Event Listener Registration"
    language: php
    file_pattern: "**/EventServiceProvider.php"
    match:
      type: regex
      pattern: "([\\w\\\\]+)::class\\s*=>\\s*\\[([^\\]]+)\\]"
    captures:
      - name: event_class
        group: 1
        transform: resolve_class
      - name: listeners
        group: 2
    creates:
      node:
        type: event
        id: "event:$event_class"
        singleton: true
        properties:
          class: $event_class
```

---

## Implementation Notes

### Hot Reload

The file watcher enables interactive pattern development:

```
┌─────────────────────────────────────────────────────────────────┐
│  Developer Workflow                                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. emerge scan /path/to/project                                │
│  2. emerge watcher start                                        │
│  3. emerge viewer open          → D3 graph in browser           │
│                                                                  │
│  4. Edit .emerge/patterns.yaml  → Watcher detects change        │
│                                  → Patterns reloaded            │
│                                  → Affected files re-parsed     │
│                                  → Graph diff computed          │
│                                  → WebSocket pushes update      │
│                                  → D3 viewer animates changes   │
│                                                                  │
│  5. Edit src/MyClass.php        → Same flow, patterns applied   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Watcher behavior for patterns.yaml:**

| Change | Action |
|--------|--------|
| Pattern added | Re-scan all files matching pattern's `file_pattern` |
| Pattern modified | Re-scan affected files, diff nodes/edges |
| Pattern removed | Remove nodes/edges created by that pattern |
| Syntax error | Log warning, keep previous patterns active |

**Incremental updates:**

```python
# Pseudocode for pattern hot-reload
def on_patterns_changed(old_patterns, new_patterns):
    added = new_patterns - old_patterns
    removed = old_patterns - new_patterns
    modified = find_modified(old_patterns, new_patterns)

    # Remove stale nodes/edges from removed/modified patterns
    for pattern in removed | modified:
        graph.remove_nodes_by_source(pattern.id)

    # Re-scan for added/modified patterns
    for pattern in added | modified:
        files = glob(pattern.file_pattern)
        for file in files:
            matches = pattern.match(file.content)
            graph.add_nodes(matches)

    # Recompute edges
    apply_edge_rules(new_patterns.edges)

    # Push to viewers
    websocket.broadcast(graph.diff())
```

**Pattern metadata tracking:**

Each node/edge stores its source pattern:

```python
node = {
    "id": "listener:src/plugin.php:42",
    "type": "hook_listener",
    "properties": {...},
    "_meta": {
        "source_pattern": "wp_add_action",  # Which pattern created this
        "source_file": "src/plugin.php",
        "source_line": 42,
        "created_at": "2025-12-17T10:30:00Z"
    }
}
```

This enables:
- Removing nodes when patterns change
- Showing "created by pattern X" in viewer tooltips
- Debugging which pattern matched what

### Loading Order

1. Load built-in language definitions
2. Scan for `.emerge/patterns.yaml`
3. Validate schema
4. Merge custom patterns with defaults
5. During file parsing, apply matching patterns
6. After parsing, apply edge rules

### Performance Considerations

- Compile regex patterns once at load time
- Use file_pattern to limit pattern application scope
- Cache pattern matches per file
- Lazy edge resolution (build edges after all nodes exist)

### WebSocket Streaming (Performance Fix)

The current viewer takes 20+ seconds because it sends the entire graph in one JSON message. Fix with true streaming - one node/edge per message, no batching, no artificial delays.

**Protocol:**

```
Server → Client: { type: "graph_start", graph: "name", node_count: 5000, edge_count: 12000 }
Server → Client: { type: "node", id: "src/main.py", label: "main.py", cluster: 0 }
Server → Client: { type: "node", id: "src/utils.py", label: "utils.py", cluster: 0 }
... (one message per node)
Server → Client: { type: "edge", source: "src/main.py", target: "src/utils.py" }
... (one message per edge)
Server → Client: { type: "graph_end" }
```

**Design principles:**

| Principle | Implementation |
|-----------|----------------|
| No batching | One node/edge per message - simpler, no artificial grouping |
| No sleeps | `await send()` yields naturally on backpressure |
| Non-blocking | Async all the way - server handles other requests |
| Decoupled render | Client renders on `requestAnimationFrame`, not on message |

**Server implementation:**

```python
async def _stream_graph(self, websocket, graph_name: str) -> None:
    """Stream graph - one message per node/edge, fully async, non-blocking."""
    graph = self.graphs[graph_name]

    # 1. Metadata first - client knows total count for progress
    await websocket.send(json.dumps({
        "type": "graph_start",
        "graph": graph_name,
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges()
    }))

    # 2. Stream each node - no batching, no sleep
    # await is non-blocking: returns immediately if buffer has space,
    # yields to event loop only when TCP buffer is full (backpressure)
    for node, attrs in graph.nodes(data=True):
        await websocket.send(json.dumps({
            "type": "node",
            "id": node,
            "label": attrs.get("display_name", node.split("/")[-1]),
            "cluster": attrs.get("metric_louvain_modularity", 0)
        }))

    # 3. Stream each edge
    for src, tgt in graph.edges():
        await websocket.send(json.dumps({
            "type": "edge",
            "source": src,
            "target": tgt
        }))

    # 4. Signal completion
    await websocket.send(json.dumps({
        "type": "graph_end",
        "graph": graph_name
    }))
```

**Why this doesn't block:**

```
┌─────────────────────────────────────────────────────────────────┐
│  await websocket.send(data)                                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Buffer has space?  ──YES──►  Returns immediately (microseconds) │
│         │                                                        │
│         NO                                                       │
│         │                                                        │
│         ▼                                                        │
│  Yields to event loop (handles other connections)               │
│         │                                                        │
│         ▼                                                        │
│  Resumes when buffer drains (TCP sent data)                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Client implementation - decoupled architecture:**

```javascript
// ============================================
// State - message handler only writes here
// ============================================
const graphState = {
    nodes: [],
    edges: [],
    nodeCount: 0,
    edgeCount: 0,
    ready: false
};

// ============================================
// Message handler - fast, just pushes to arrays
// ============================================
ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);

    switch (msg.type) {
        case 'graph_start':
            graphState.nodes = [];
            graphState.edges = [];
            graphState.nodeCount = msg.node_count;
            graphState.edgeCount = msg.edge_count;
            graphState.ready = false;
            break;

        case 'node':
            // Just push - no rendering here
            graphState.nodes.push({
                ...msg,
                x: Math.random() * width,
                y: Math.random() * height
            });
            break;

        case 'edge':
            // Just push - no rendering here
            graphState.edges.push(msg);
            break;

        case 'graph_end':
            graphState.ready = true;
            break;
    }
};

// ============================================
// Render loop - completely decoupled from messages
// Runs at 60fps, picks up whatever data is available
// ============================================
let lastNodeCount = 0;
let lastEdgeCount = 0;

function renderLoop() {
    // Only update simulation when new data arrived
    if (graphState.nodes.length !== lastNodeCount) {
        simulation.nodes(graphState.nodes);
        lastNodeCount = graphState.nodes.length;
    }

    if (graphState.edges.length !== lastEdgeCount) {
        simulation.force("link").links(graphState.edges);
        lastEdgeCount = graphState.edges.length;
    }

    // Keep simulation warm while streaming
    if (!graphState.ready && graphState.nodes.length > 0) {
        simulation.alpha(0.1).restart();
    }

    // Final settle when complete
    if (graphState.ready && simulation.alpha() < 0.01) {
        simulation.alpha(0.3).restart();
    }

    // Update progress indicator
    updateProgress(
        graphState.nodes.length + graphState.edges.length,
        graphState.nodeCount + graphState.edgeCount
    );

    requestAnimationFrame(renderLoop);
}

// Start render loop once
requestAnimationFrame(renderLoop);
```

**Visual effect:**

The graph "grows" organically:
1. Nodes pop in one by one, scattered randomly
2. D3 force simulation pulls them into clusters
3. Edges appear and connect nodes
4. Link forces pull connected nodes together
5. Clusters form visually as you watch

**Performance comparison:**

| Metric | Before (monolithic) | After (streaming) |
|--------|---------------------|-------------------|
| Time to first node | 20+ seconds | < 50ms |
| UI responsiveness | Frozen | Always smooth |
| Memory spike | High (full JSON) | Minimal (one msg) |
| Visual feedback | None | Graph grows live |
| Server blocking | Yes (builds payload) | No (async stream) |

**Additional optimizations (optional):**

1. **WebSocket compression** - built-in, nearly free:
   ```python
   async with websockets.serve(handler, host, port, compression="deflate"):
   ```

2. **Binary format** - 2-5x smaller messages:
   ```python
   import msgpack
   await websocket.send(msgpack.packb({"type": "node", ...}))
   ```
   ```javascript
   ws.binaryType = 'arraybuffer';
   ws.onmessage = (e) => {
       const msg = msgpack.decode(new Uint8Array(e.data));
   };
   ```

3. **Lazy attribute loading** - minimal data on stream, full on hover:
   - Stream: `id`, `label`, `cluster` only
   - On hover: `get_node` fetches full metrics

4. **Throttled simulation updates** - if messages arrive faster than 60fps:
   ```javascript
   // Batch simulation updates to animation frames
   let pendingUpdate = false;

   ws.onmessage = (e) => {
       // ... push to arrays ...
       if (!pendingUpdate) {
           pendingUpdate = true;
           requestAnimationFrame(() => {
               simulation.nodes(graphState.nodes);
               simulation.force("link").links(graphState.edges);
               pendingUpdate = false;
           });
       }
   };
   ```

### Error Handling

```yaml
# In patterns.yaml
settings:
  on_pattern_error: warn    # warn | error | ignore
  on_capture_missing: skip  # skip | default | error
  strict_mode: false        # Fail on any validation error
```

### Debugging

```bash
# Test patterns against a file
emerge patterns test --file src/MyClass.php --pattern wp_add_action

# Show what patterns would match
emerge patterns match --file src/MyClass.php --verbose

# Validate patterns.yaml
emerge patterns validate

# List loaded patterns
emerge patterns list
```

---

## CLI Integration

```bash
# Initialize patterns for a framework
emerge init --framework wordpress
emerge init --framework laravel

# This creates .emerge/patterns.yaml with framework defaults

# Scan with custom patterns
emerge scan --patterns .emerge/patterns.yaml

# Export discovered nodes/edges
emerge export --format json --include-custom-nodes
```

---

## Future Extensions

### 1. Pattern Sharing

```bash
# Install community patterns
emerge patterns install wordpress
emerge patterns install laravel

# Patterns stored in ~/.emerge/patterns/
```

### 2. AST Patterns

Move beyond regex to actual AST matching for better accuracy:

```yaml
match:
  type: ast
  language: php
  pattern:
    node: function_call
    name:
      type: name
      value: add_action
    args:
      - type: string
        capture: hook_name
      - capture: callback
```

### 3. Cross-File Resolution

```yaml
patterns:
  - id: class_instantiation
    creates:
      edge:
        from: $current_file
        to:
          resolve: class  # Emerge resolves to actual file
          value: $class_name
```

---

## Migration Path

### Phase 1: Regex Patterns
- Pattern matching via regex
- Simple node/edge creation
- Property-based edge matching

### Phase 2: Transforms & Resolution
- Class name resolution
- Namespace awareness
- Callable extraction

### Phase 3: AST Patterns
- Tree-sitter integration
- Structural matching
- Type-aware patterns

### Phase 4: Semantic Patterns
- Cross-file type resolution
- Interface/implementation tracking
- Full DI container understanding

---

## Open Questions

1. **Pattern priority**: When multiple patterns match, which wins?
2. **Pattern inheritance**: Can patterns extend other patterns?
3. **Conditional patterns**: Patterns that only apply if another pattern matched?
4. **Pattern groups**: Enable/disable groups of patterns together?
5. **Performance**: At what point do we need pattern compilation/optimization?

---

## References

- [Semgrep Rules](https://semgrep.dev/docs/writing-rules/rule-syntax/) - Similar pattern syntax
- [Tree-sitter Queries](https://tree-sitter.github.io/tree-sitter/using-parsers#pattern-matching-with-queries) - AST pattern matching
- [CodeQL](https://codeql.github.com/) - Semantic code analysis patterns
