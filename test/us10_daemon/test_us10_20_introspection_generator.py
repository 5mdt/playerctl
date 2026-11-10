"""US-10.20: As a maintainer, I want the build to refuse to generate
introspection data that excludes a member the specification does not have, so
that a renamed or removed member can never silently end up announced."""

import re
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / 'playerctl' / 'gen-introspection-header.py'
SPEC_XML = ROOT / 'data' / 'mpris-dbus-interface.xml'

FIXTURE = """<node>
  <interface name="org.example.Thing">
    <method name="Poke"/>
    <method name="Fetch">
      <arg direction="out" type="h" name="Handle"/>
    </method>
    <signal name="Poked"/>
    <property name="Mood" type="s" access="read">
      <annotation name="org.example.Note" value="say &quot;hi&quot; \\ bye"/>
    </property>
  </interface>
</node>
"""

LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')
ESCAPES = {'n': '\n', 't': '\t'}


def run(
    source,
    output,
    *excludes,
    variable='mpris_introspection_xml',
    aliases=(),
):
    command = [
        sys.executable,
        str(GENERATOR),
        str(source),
        str(output),
        '--variable',
        variable,
    ]
    for exclude in excludes:
        command += ['--exclude', exclude]
    for alias in aliases:
        command += ['--deprecated-alias', alias]
    return subprocess.run(command, capture_output=True, text=True)


def decode(header):
    '''The XML held by the C string literals of a generated header.'''
    value = header.split('=', 1)[1]
    text = ''.join(LITERAL.findall(value))
    return re.sub(r'\\(.)', lambda m: ESCAPES.get(m[1], m[1]), text)


def canonical(xml):
    return ElementTree.canonicalize(xml, strip_text=True)


def generate(tmp_path, source_text, *excludes, **options):
    source = tmp_path / 'in.xml'
    source.write_text(source_text)
    output = tmp_path / 'out.h'
    result = run(source, output, *excludes, **options)
    return result, output


def test_the_header_defines_the_introspection_string(tmp_path):
    result, output = generate(tmp_path, FIXTURE)

    assert result.returncode == 0, result.stderr
    header = output.read_text()
    assert 'static const char mpris_introspection_xml[]' in header
    assert canonical(decode(header)) == canonical(FIXTURE)


def test_the_variable_name_is_chosen_by_the_caller(tmp_path):
    result, output = generate(tmp_path, FIXTURE, variable='thing_xml')

    assert result.returncode == 0, result.stderr
    header = output.read_text()
    assert 'static const char thing_xml[]' in header
    assert 'mpris_introspection_xml' not in header


def test_the_variable_name_is_required(tmp_path):
    source = tmp_path / 'in.xml'
    source.write_text(FIXTURE)

    result = subprocess.run(
        [sys.executable, str(GENERATOR), str(source), str(tmp_path / 'o.h')],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert '--variable' in result.stderr


def test_quotes_and_backslashes_survive_the_c_escaping(tmp_path):
    result, output = generate(tmp_path, FIXTURE)

    assert result.returncode == 0, result.stderr
    node = ElementTree.fromstring(decode(output.read_text()))
    note = node.find('.//annotation')
    assert note.get('value') == 'say "hi" \\ bye'


def test_excluded_members_are_removed(tmp_path):
    result, output = generate(
        tmp_path,
        FIXTURE,
        'org.example.Thing.Fetch',
        'org.example.Thing.Poked',
        'org.example.Thing.Mood',
    )

    assert result.returncode == 0, result.stderr
    node = ElementTree.fromstring(decode(output.read_text()))
    interface = node.find("interface[@name='org.example.Thing']")
    assert [m.get('name') for m in interface.findall('method')] == ['Poke']
    assert interface.findall('signal') == []
    assert interface.findall('property') == []


def test_excluding_a_missing_member_fails_the_build(tmp_path):
    result, output = generate(tmp_path, FIXTURE, 'org.example.Thing.Gone')

    assert result.returncode != 0
    assert 'org.example.Thing.Gone' in result.stderr
    assert not output.exists()


def test_excluding_from_a_missing_interface_fails_the_build(tmp_path):
    result, output = generate(tmp_path, FIXTURE, 'org.example.Other.Poke')

    assert result.returncode != 0
    assert 'org.example.Other.Poke' in result.stderr
    assert not output.exists()


def aliased(tmp_path, *excludes, aliases):
    result, output = generate(tmp_path, FIXTURE, *excludes, aliases=aliases)
    assert result.returncode == 0, result.stderr
    return ElementTree.fromstring(decode(output.read_text()))


def test_a_deprecated_alias_is_a_marked_copy_of_the_interface(tmp_path):
    node = aliased(
        tmp_path, aliases=['org.example.Thing=org.example.OldThing']
    )

    names = [i.get('name') for i in node.findall('interface')]
    assert names == ['org.example.Thing', 'org.example.OldThing']
    original, alias = node.findall('interface')
    marker = "annotation[@name='org.freedesktop.DBus.Deprecated']"
    assert original.find(marker) is None
    assert alias.find(marker).get('value') == 'true'
    for kind in ('method', 'signal', 'property'):
        assert [e.get('name') for e in alias.findall(kind)] == [
            e.get('name') for e in original.findall(kind)
        ]


def test_exclusions_apply_to_the_alias_too(tmp_path):
    node = aliased(
        tmp_path,
        'org.example.Thing.Poke',
        aliases=['org.example.Thing=org.example.OldThing'],
    )

    for interface in node.findall('interface'):
        methods = [m.get('name') for m in interface.findall('method')]
        assert methods == ['Fetch']


def test_an_alias_of_a_missing_interface_fails_the_build(tmp_path):
    result, output = generate(
        tmp_path, FIXTURE, aliases=['org.example.Gone=org.example.OldGone']
    )

    assert result.returncode != 0
    assert 'no interface org.example.Gone' in result.stderr
    assert not output.exists()


def test_an_alias_must_not_reuse_an_existing_interface_name(tmp_path):
    result, output = generate(
        tmp_path, FIXTURE, aliases=['org.example.Thing=org.example.Thing']
    )

    assert result.returncode != 0
    assert 'org.example.Thing already exists' in result.stderr
    assert not output.exists()


def test_the_specification_still_has_the_excluded_member(tmp_path):
    # the member playerctl/meson.build excludes must exist in the vendored spec,
    # or the build would fail (or, worse, an exclusion would go unnoticed)
    output = tmp_path / 'out.h'

    result = run(
        SPEC_XML, output, 'org.mpris.MediaPlayer2.Player.GetArtworkFd'
    )

    assert result.returncode == 0, result.stderr
    assert 'GetArtworkFd' not in decode(output.read_text())
    assert 'GetArtworkFd' in SPEC_XML.read_text()
