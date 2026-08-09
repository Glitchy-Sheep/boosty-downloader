#!/bin/sh
# Grouped, colored task list for bare `task` (invoked by the `default` task).
#
# Input is `task --list --json`, not the human-readable `--list` table: the JSON
# is a machine-readable contract, and name/desc arrive as separate fields.
#
# Grouping rules:
# - a group is the name segment before the first ':' (build:dist:all -> build)
# - a colon-less task joins the same-named group when one exists (build, lint);
#   otherwise it lands in a trailing `misc` bucket (test, clean)
# - inside a group, tasks are split into blocks by their second segment, but a
#   blank line is only drawn where a block holds more than one task
# - group order and in-group order follow Taskfile definition order (--sort none)
#
# TASKLIST_EMOJI maps groups to header icons ("build=🔨 misc=🧰");
# a group with no entry falls back to a plain arrow.
set -eu

# Color: on for a tty; FORCE_COLOR (the variable task honors) or
# CLICOLOR_FORCE forces on; NO_COLOR wins over everything.
color=1
[ -t 1 ] || color=0
if [ "${FORCE_COLOR:-0}" != 0 ] || [ "${CLICOLOR_FORCE:-0}" != 0 ]; then color=1; fi
if [ -n "${NO_COLOR:-}" ]; then color=0; fi

# Soft 256-color palette when the terminal advertises it, base ANSI otherwise.
palette=16
case "${COLORTERM:-}:${TERM:-}" in *truecolor* | *24bit* | *256color*) palette=256 ;; esac

# Keep the command substitution: a pipe would swallow the exit code of task.
tasks_json="$(task --list --json --sort none)" || exit $?

printf '%s\n' "$tasks_json" | awk -v color="$color" -v palette="$palette" '
BEGIN {
  MISC = "\001"   # misc bucket key; a control char cannot collide with a task name
  TITLE = "Boosty Downloader · task <name> [-- args]"
  KEY_NAME = "\"name\"[ \t]*:"
}

# Slurp the payload: JSON strings never span lines, so joining with a space is safe.
{ json = json $0 " " }

END {
  parse_tasks(json)
  parse_emoji(ENVIRON["TASKLIST_EMOJI"])
  set_colors()
  build_groups()
  render()
}

# --- input ------------------------------------------------------------------

# Cuts the payload into one chunk per task object and reads the fields out of
# each. A chunk runs from one "name" key to the next; this relies on "name"
# being the first string field of a task object, which is how task emits it.
function parse_tasks(payload,   tail, chunk) {
  if (!match(payload, KEY_NAME)) return
  payload = substr(payload, RSTART)
  while (payload != "") {
    tail = substr(payload, 2)               # step over the current key
    if (match(tail, KEY_NAME)) {
      chunk = substr(payload, 1, RSTART)
      payload = substr(tail, RSTART)
    } else {
      chunk = payload
      payload = ""
    }
    add_task(chunk)
  }
}

function add_task(chunk,   name) {
  name = string_field(chunk, "name")
  if (name == "" || name == "default") return   # do not list the lister itself
  ntasks++
  names[ntasks] = name
  descs[ntasks] = string_field(chunk, "desc") alias_suffix(chunk)
  if (length(name) > namewidth) namewidth = length(name)
}

# Value of a "<key>": "<value>" pair, JSON-unescaped. Empty when the key is absent.
function string_field(chunk, key,   hit) {
  if (!match(chunk, "\"" key "\"[ \t]*:[ \t]*\"([^\"\\\\]|\\\\.)*\"")) return ""
  hit = substr(chunk, RSTART, RLENGTH)
  sub(/^[^:]*:[ \t]*"/, "", hit)            # drop the key and the opening quote
  sub(/"$/, "", hit)
  return json_unescape(hit)
}

# Aliases rendered as "  (aliases: a, b)", the suffix `task --list` appends to a
# description. Empty when the task has none.
function alias_suffix(chunk,   body, n, i, item, out) {
  if (!match(chunk, /"aliases"[ \t]*:[ \t]*\[[^]]*\]/)) return ""
  body = substr(chunk, RSTART, RLENGTH)
  sub(/^[^[]*\[/, "", body)
  sub(/\]$/, "", body)
  n = split(body, item, ",")
  for (i = 1; i <= n; i++) {
    gsub(/^[ \t"]+|[ \t"]+$/, "", item[i])
    if (item[i] != "") out = (out == "") ? item[i] : out ", " item[i]
  }
  return (out == "") ? "" : "  (aliases: " out ")"
}

function json_unescape(s,   out, i, c, hex) {
  for (i = 1; i <= length(s); i++) {
    c = substr(s, i, 1)
    if (c != "\\") { out = out c; continue }
    i++
    c = substr(s, i, 1)
    if (c == "n" || c == "t" || c == "r") out = out " "   # keep one line per task
    else if (c == "u") {
      # Go json HTML-escapes & < > as \u00XX; other \uXXXX are not rendered.
      hex = substr(s, i + 1, 4)
      i += 4
      if (hex == "0026") out = out "&"
      else if (hex == "003c") out = out "<"
      else if (hex == "003e") out = out ">"
    }
    else out = out c                                      # \" \\ \/ and friends
  }
  return out
}

function parse_emoji(spec,   ntok, i, tok, eq) {
  ntok = split(spec, tok, " ")
  for (i = 1; i <= ntok; i++) {
    eq = index(tok[i], "=")
    if (eq) emoji[substr(tok[i], 1, eq - 1)] = substr(tok[i], eq + 1)
  }
}

# --- grouping ---------------------------------------------------------------

function head_segment(name,   i) {
  i = index(name, ":")
  return i ? substr(name, 1, i - 1) : ""
}

function second_segment(name,   i, rest, j) {
  i = index(name, ":")
  if (!i) return ""
  rest = substr(name, i + 1)
  j = index(rest, ":")
  return j ? substr(rest, 1, j - 1) : rest
}

# Assigns each task a group and a block, and counts block sizes.
# Groups keep Taskfile order; the misc bucket, when present, goes last.
function build_groups(   i, g) {
  for (i = 1; i <= ntasks; i++)
    if (head_segment(names[i]) != "") isgroup[head_segment(names[i])] = 1

  for (i = 1; i <= ntasks; i++) {
    g = head_segment(names[i])
    if (g == "") g = isgroup[names[i]] ? names[i] : MISC
    if (g == MISC && isgroup["misc"]) g = "misc"   # a real misc group absorbs the bucket
    group[i] = g
    block[i] = second_segment(names[i])
    blocksize[g SUBSEP block[i]]++
    if (g == MISC) hasmisc = 1
    else if (!(g in seen)) { seen[g] = 1; grouporder[++ngroups] = g }
  }
  if (hasmisc) grouporder[++ngroups] = MISC
}

# --- output -----------------------------------------------------------------

function set_colors() {
  if (!color) { HEAD = ""; NAME = ""; DIM = ""; RESET = ""; return }
  if (palette == 256) { HEAD = "\033[1;38;5;75m"; NAME = "\033[38;5;80m"; DIM = "\033[38;5;242m" }
  else                { HEAD = "\033[1;34m";      NAME = "\033[36m";      DIM = "\033[2m" }
  RESET = "\033[0m"
}

function render(   fmt, gi, g, label, i, prev, first) {
  # Width is baked into the format: busybox awk rejects the "%-*s" specifier.
  fmt = "    %s·%s %s%-" namewidth "s%s  %s\n"
  printf "%s%s%s\n", DIM, TITLE, RESET
  for (gi = 1; gi <= ngroups; gi++) {
    g = grouporder[gi]
    label = (g == MISC) ? "misc" : g
    printf "\n%s %s%s%s\n", (label in emoji ? emoji[label] : "▸"), HEAD, label, RESET

    prev = ""; first = 1
    for (i = 1; i <= ntasks; i++) {
      if (group[i] != g) continue
      if (!first && block[i] != prev && \
          (blocksize[g SUBSEP block[i]] > 1 || blocksize[g SUBSEP prev] > 1)) print ""
      printf fmt, DIM, RESET, NAME, names[i], RESET, descs[i]
      prev = block[i]; first = 0
    }
  }
}'
