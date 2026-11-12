"""Classify a Bash command without keeping it.

Searches and file reads mostly hide inside Bash (docs/SCHEMA.md section 7). This module splits a
command into parts and decides what kind of work it did. Only three things leave it: a kind, the
sanitized command words, and file-path-looking arguments of read commands. Nothing from a quoted
string, a heredoc body, an inline script, or a comment is ever kept. When unsure, keep nothing.

The rules, in plain words (docs/METHOD.md repeats them):
1. Split at &&, ||, ;, |, &, and newlines. Look only at each part's command word.
2. WORD_KINDS maps command words to a kind. Words such as cd and export decide nothing.
3. If the parts disagree, the FIRST part that decides wins ("grep x | head" is a search).
4. A part that redirects output into a file (> or >>), or runs sed -i, is a write.
5. If no part decides, the command is "other command".
"""
import os
import re

SEARCH, READ, RUN, WRITE, WEB, OTHER = 'search', 'read_file', 'run_command', 'write_edit', 'web', 'other_command'
DECISIVE = (SEARCH, READ, RUN, WRITE, WEB)

_ENV_ASSIGNMENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')
_SAFE_WORD = re.compile(r'^[A-Za-z0-9._+-]{1,40}$')
_PATH_CHARS = re.compile(r'^[\w.@+~/-]{1,200}$')
_HAS_EXTENSION = re.compile(r'[\w-]\.[A-Za-z][A-Za-z0-9]{0,5}$')
_SCRIPT_NAME = re.compile(r'\.(sh|py|js|rb)$')
_MAX_WORDS, _MAX_PATHS = 5, 20


def _kinds(kind, words):
    """Map each word in a space-separated string to one kind."""
    return {word: kind for word in words.split()}


# The one table of command words. None means the word decides nothing.
WORD_KINDS = {}
WORD_KINDS.update(_kinds(SEARCH, 'grep egrep fgrep rg ag ack find fd ls tree locate'))
WORD_KINDS.update(_kinds(READ, 'cat head tail sed awk wc less more bat nl jq sort uniq cut tr '
                               'diff cmp xxd strings od column fold rev stat'))
WORD_KINDS.update(_kinds(RUN, 'python python3 node npm npx yarn pnpm pytest make cargo go java javac '
                              'ruby bash sh zsh git gh pip pip3 uv poetry tsc vite docker brew '
                              'claude open kill pkill lsof ps swift xcodebuild gradle mvn dotnet '
                              'php perl tsx deno bun rustc gcc clang cmake unzip zip tar osascript '
                              'code mdfind say afplay screencapture sips psql eval xcrun launchctl supabase'))
WORD_KINDS.update(_kinds(WRITE, 'mkdir touch cp mv rm rmdir ln chmod chown install'))
WORD_KINDS.update(_kinds(WEB, 'curl wget http https dig'))
WORD_KINDS.update(_kinds(None, 'cd export set unset echo printf true false test [ [[ source . pwd '
                               'which type env alias wait sleep exit trap ulimit clear date read '
                               'for while until if then else elif fi do done case esac in function '
                               'select { } ( ) ! return break continue local declare unalias hash '
                               'tput stty basename dirname realpath readlink'))
_SKIP_PREFIX = set('sudo time nohup exec command nice xargs timeout do then else elif if while until ! { ('
                   .split())


# ---------------------------------------------------------------- splitting

class _Scanner:
    """Walks a command once, producing parts. Quoted text and heredoc bodies are never kept."""

    def __init__(self, command):
        self.s, self.n, self.i = command, len(command), 0
        self.parts, self.tokens, self.cur = [], [], []
        self.quoted = False
        self.write = False
        self.heredocs = []

    def end_token(self):
        """Close the current word, if there is one."""
        if self.cur or self.quoted:
            self.tokens.append({'text': ''.join(self.cur), 'quoted': self.quoted})
        self.cur, self.quoted = [], False

    def end_part(self):
        """Close the current part (a command between separators)."""
        self.end_token()
        if self.tokens or self.write:
            self.parts.append({'tokens': self.tokens, 'write': self.write})
        self.tokens, self.write = [], False

    def skip_quoted(self, quote):
        """Skip a quoted string or backtick span; its content is dropped."""
        self.quoted = True
        j = self.i + 1
        while j < self.n and self.s[j] != quote:
            j += 2 if self.s[j] == '\\' and quote == '"' else 1
        self.i = min(j + 1, self.n)

    def skip_substitution(self):
        """Skip $( ... ) with nested parentheses; its content is dropped."""
        self.quoted = True
        depth, j = 0, self.i + 1
        while j < self.n:
            depth += self.s[j] == '('
            depth -= self.s[j] == ')'
            j += 1
            if depth == 0:
                break
        self.i = j

    def skip_target(self):
        """Skip the word after a redirect; it is not an argument."""
        while self.i < self.n and self.s[self.i] in ' \t':
            self.i += 1
        if self.i < self.n and self.s[self.i] in '"\'':
            self.skip_quoted(self.s[self.i])
            self.quoted = False
            return
        start = self.i
        while self.i < self.n and self.s[self.i] not in ' \t\n;|&<>':
            self.i += 1
        return self.s[start:self.i]

    def redirect_out(self):
        """Handle > and >>. A redirect to a file is a write; 2>&1 and /dev/null are not."""
        if self.cur and ''.join(self.cur).isdigit() and not self.quoted:
            self.cur = []  # a file descriptor number such as the 2 in 2>
        self.end_token()
        self.i += 1
        while self.i < self.n and self.s[self.i] in '>|':
            self.i += 1
        if self.i < self.n and self.s[self.i] == '&':
            self.i += 1
            while self.i < self.n and (self.s[self.i].isdigit() or self.s[self.i] == '-'):
                self.i += 1
            return
        target = self.skip_target()
        if target != '/dev/null':
            self.write = True

    def redirect_in(self):
        """Handle < (input file), << (heredoc: body is dropped), and <<< (here-string)."""
        self.end_token()
        if self.s.startswith('<<<', self.i):
            self.i += 3
            return
        if not self.s.startswith('<<', self.i):
            self.i += 1
            self.skip_target()
            return
        self.i += 2
        strip_tabs = self.i < self.n and self.s[self.i] == '-'
        self.i += strip_tabs
        while self.i < self.n and self.s[self.i] in ' \t':
            self.i += 1
        quote = self.s[self.i] if self.i < self.n and self.s[self.i] in '"\'' else None
        start = self.i + (quote is not None)
        end = self.s.find(quote, start) if quote else start
        if not quote:
            while end < self.n and not self.s[end] in ' \t\n;|&<>':
                end += 1
        elif end < 0:
            end = self.n
        self.heredocs.append((self.s[start:end], strip_tabs))
        self.i = end + (quote is not None)

    def skip_heredoc_bodies(self):
        """After a newline, drop every line up to and including each pending delimiter."""
        for delimiter, strip_tabs in self.heredocs:
            while self.i < self.n:
                stop = self.s.find('\n', self.i)
                stop = self.n if stop < 0 else stop
                line = self.s[self.i:stop]
                self.i = min(stop + 1, self.n)
                if (line.lstrip('\t') if strip_tabs else line) == delimiter:
                    break
        self.heredocs = []

    def run(self):
        """Scan the whole command and return its parts."""
        while self.i < self.n:
            ch = self.s[self.i]
            nxt = self.s[self.i + 1] if self.i + 1 < self.n else ''
            if ch == '\\':
                if nxt != '\n':
                    self.cur.append(nxt)
                self.i += 2
            elif ch in '\'"`':
                self.skip_quoted(ch)
            elif ch == '$' and nxt == '(':
                self.skip_substitution()
            elif ch == '#' and not self.cur and not self.quoted and (
                    self.i == 0 or self.s[self.i - 1] in ' \t\n;|&('):
                stop = self.s.find('\n', self.i)
                self.i = self.n if stop < 0 else stop
            elif ch in ' \t':
                self.end_token()
                self.i += 1
            elif ch == '\n':
                self.end_part()
                self.i += 1
                if self.heredocs:
                    self.skip_heredoc_bodies()
            elif ch in ';|':
                self.end_part()
                self.i += 2 if nxt in '|&' and ch == '|' else 1
            elif ch == '&':
                if nxt == '>':
                    self.i += 1
                    self.redirect_out()
                else:
                    self.end_part()
                    self.i += 2 if nxt == '&' else 1
            elif ch == '>':
                self.redirect_out()
            elif ch == '<':
                self.redirect_in()
            else:
                self.cur.append(ch)
                self.i += 1
        self.end_part()
        return self.parts


# ---------------------------------------------------------------- classifying

def first_word(text):
    """Return only the first word of a shell command, skipping VAR=value prefixes.

    This is the rule the parser has used since prompt 3: path stripped, nothing else kept.
    """
    if not isinstance(text, str):
        return None
    for token in text.split():
        if _ENV_ASSIGNMENT.match(token):
            continue
        word = os.path.basename(token.lstrip('({!`'))
        return word if _SAFE_WORD.match(word) else '?'
    return None


def _command_word(tokens):
    """Return (word, index of the word in tokens) for a part, or (None, -1) if it has none."""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token['quoted'] and _ENV_ASSIGNMENT.match(token['text']):
            index += 1
            continue
        stripped = token['text'].strip('(){}') if not token['quoted'] else ''
        if not token['quoted'] and token['text'] and not stripped:
            index += 1  # a lone ( or { opens a group; the command follows
            continue
        word = os.path.basename(stripped) if not token['quoted'] else '?'
        if word in _SKIP_PREFIX and not token['quoted']:
            index += 1
            while word == 'timeout' and index < len(tokens) and tokens[index]['text'].replace('.', '').isdigit():
                index += 1
            continue
        return (word if _SAFE_WORD.match(word) else '?'), index
    return None, -1


def _part_kind(part, word, index):
    """The kind of one part: a write if it redirects into a file, else the word's kind."""
    args = part['tokens'][index + 1:]
    if part['write']:
        return WRITE
    if word == 'sed' and any(not a['quoted'] and (a['text'] == '--in-place' or re.match(r'^-i', a['text'])) for a in args):
        return WRITE
    if word not in WORD_KINDS and _SCRIPT_NAME.search(word):
        return RUN  # a script such as ./deploy.sh or build.py
    return WORD_KINDS.get(word)


def _looks_like_path(token):
    """True for an unquoted argument that clearly names a file. When unsure, False."""
    text = token['text']
    if token['quoted'] or text.startswith('-') or not _PATH_CHARS.match(text):
        return False
    return '/' in text or bool(_HAS_EXTENSION.search(text))


def analyze_command(command):
    """Return {'kind', 'words', 'paths'} for a Bash command string. Keeps nothing else."""
    kind, words, paths = OTHER, [], []
    if not isinstance(command, str):
        return {'kind': kind, 'words': words, 'paths': paths}
    decided = False
    for part in _Scanner(command).run():
        word, index = _command_word(part['tokens'])
        if word is None and not part['write']:
            continue
        part_kind = _part_kind(part, word or '?', index if index >= 0 else 0)
        if part_kind is not None and word is not None and word not in words and len(words) < _MAX_WORDS:
            words.append(word)
        elif part_kind is None and word not in WORD_KINDS and word not in (None, '?') and len(words) < _MAX_WORDS:
            if word not in words:
                words.append(word)
        if part_kind in DECISIVE and not decided:
            kind, decided = part_kind, True
        if part_kind == READ:
            for token in part['tokens'][index + 1:]:
                if _looks_like_path(token) and token['text'] not in paths and len(paths) < _MAX_PATHS:
                    paths.append(token['text'])
    return {'kind': kind, 'words': words, 'paths': paths}
