"""Tests for src/bash.py: the Bash command table and its privacy rules."""
import json
import unittest

from src import bash, parse
from tests.helpers import SESSION_3


def kind(command):
    return bash.analyze_command(command)['kind']


class KindTest(unittest.TestCase):
    def test_pipes_and_and_split_into_parts(self):
        self.assertEqual(kind('grep -rn foo src | head -5'), bash.SEARCH)
        self.assertEqual(kind('cd /x && python3 -m pytest -q 2>&1 | tail -20'), bash.RUN)
        self.assertEqual(kind('false || cat notes.md'), bash.READ)
        self.assertEqual(kind('ls -la; wc -l a.py'), bash.SEARCH)
        self.assertEqual(kind('mkdir -p out && cp a.py out/'), bash.WRITE)
        self.assertEqual(kind('curl -s example.com | jq .a'), bash.WEB)

    def test_first_deciding_part_wins_when_parts_disagree(self):
        self.assertEqual(kind('cat a.py | grep x'), bash.READ)
        self.assertEqual(kind('grep x a.py | cat'), bash.SEARCH)
        self.assertEqual(kind('cd src && grep x a.py'), bash.SEARCH)  # cd decides nothing

    def test_words_that_decide_nothing_and_unknown_commands(self):
        self.assertEqual(kind('cd /tmp'), bash.OTHER)
        self.assertEqual(kind('export A=1'), bash.OTHER)
        self.assertEqual(kind('some-unknown-tool --flag'), bash.OTHER)
        self.assertEqual(kind('some-unknown-tool && grep x y'), bash.SEARCH)
        self.assertEqual(kind('./deploy.sh'), bash.RUN)
        self.assertEqual(kind(None), bash.OTHER)
        self.assertEqual(kind(''), bash.OTHER)

    def test_env_prefixes_are_skipped(self):
        result = bash.analyze_command('FOO=1 BAR=2 /usr/bin/grep -n x file.py')
        self.assertEqual((result['kind'], result['words']), (bash.SEARCH, ['grep']))
        self.assertEqual(kind('sudo make'), bash.RUN)  # a prefix word is skipped
        self.assertEqual(kind('time python3 x.py'), bash.RUN)

    def test_redirects_make_a_write_but_not_dev_null_or_fd_copies(self):
        self.assertEqual(kind('echo hi > out.txt'), bash.WRITE)
        self.assertEqual(kind('python3 run.py >> log.txt'), bash.WRITE)
        self.assertEqual(kind('python3 run.py > /dev/null'), bash.RUN)
        self.assertEqual(kind('python3 run.py 2>&1'), bash.RUN)
        self.assertEqual(kind("sed -n '1,5p' a.md"), bash.READ)
        self.assertEqual(kind("sed -i 's/a/b/' a.md"), bash.WRITE)

    def test_read_commands_keep_only_clear_file_paths(self):
        self.assertEqual(bash.analyze_command('cat src/a.py tests/c.txt')['paths'], ['src/a.py', 'tests/c.txt'])
        self.assertEqual(bash.analyze_command("sed -n '1,5p' notes.md")['paths'], ['notes.md'])
        self.assertEqual(bash.analyze_command('head -n 20 build.log')['paths'], ['build.log'])
        self.assertEqual(bash.analyze_command('tail -f logfile')['paths'], [])  # unsure: keep nothing
        self.assertEqual(bash.analyze_command('cat "my file.txt"')['paths'], [])  # quoted: keep nothing
        self.assertEqual(bash.analyze_command('cat $FILE src/*.py')['paths'], [])
        self.assertEqual(bash.analyze_command('grep x src/a.py')['paths'], [])  # a search, not a read
        self.assertEqual(bash.analyze_command('curl x | jq .a')['paths'], [])


class PrivacyTest(unittest.TestCase):
    SECRETS = ('SECRET-BODY', 'SECRET-INLINE', 'SECRET-QUOTED', 'SECRET-COMMENT', 'SECRET-SUB')

    def check(self, command):
        dumped = json.dumps(bash.analyze_command(command))
        for secret in self.SECRETS:
            self.assertNotIn(secret, dumped)

    def test_heredoc_body_is_dropped(self):
        self.check("cat > out.txt <<'EOF'\nSECRET-BODY line\nEOF\nls")
        self.check('cat <<-EOF\n\tSECRET-BODY\n\tEOF\n')
        self.assertEqual(kind("cat > out.txt <<'EOF'\nSECRET-BODY\nEOF\nls"), bash.WRITE)

    def test_inline_scripts_and_quoted_strings_are_dropped(self):
        self.check('python3 -c "print(\'SECRET-INLINE\')"')
        self.check("python3 - <<'PY'\nprint('SECRET-INLINE')\nPY")
        self.check("node -e 'console.log(\"SECRET-INLINE\")'")
        self.check('grep -E "SECRET-QUOTED|x" src/a.py')
        self.check("echo 'SECRET-QUOTED' && ls")

    def test_comments_and_substitutions_are_dropped(self):
        self.check('tail -f build.log # SECRET-COMMENT')
        self.check('$(echo SECRET-SUB) arg')
        self.check('echo `echo SECRET-SUB`')

    def test_only_sanitized_words_leave_the_module(self):
        for word in bash.analyze_command('weird$name && ok.sh')['words']:
            self.assertRegex(word, r'^[A-Za-z0-9._+-]{1,40}$')
        self.assertEqual(bash.first_word('FOO=1 /usr/bin/grep x'), 'grep')
        self.assertEqual(bash.first_word('$(evil)'), '?')


class ParsedFixtureTest(unittest.TestCase):
    def test_lowercase_bash_tool_is_classified_and_leaks_nothing(self):
        session = parse.parse_session(SESSION_3)
        tool_call = session['calls'][0]['tool_calls'][0]
        self.assertEqual(tool_call['tool'], 'Bash')  # the log says "bash"
        self.assertEqual(tool_call['bash']['kind'], bash.WRITE)  # cat > notes.txt <<EOF
        self.assertEqual(tool_call['bash']['words'], ['cat', 'python3', 'grep', 'head'])
        dumped = json.dumps(session)
        for secret in ('SECRET-HEREDOC-BODY', 'SECRET-INLINE-SCRIPT', 'SECRET-QUOTED-ARG', 'notes.txt'):
            self.assertNotIn(secret, dumped)

    def test_typed_prompts_keep_their_length_not_their_text(self):
        session = parse.parse_session(SESSION_3)
        self.assertEqual([(p['kind'], p['chars']) for p in session['prompts']], [('typed', 70), ('typed', 300)])
        self.assertNotIn('SECRET-TYPED-PROMPT', json.dumps(session))


if __name__ == '__main__':
    unittest.main()
