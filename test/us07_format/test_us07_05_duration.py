"""US-7.5: As a bar author, I want a `duration()` helper (time formatting)."""

import pytest

# microseconds -> `m:ss`, or `h:mm:ss` once an hour is reached
DURATIONS = [
    (0, '0:00'),
    (999999, '0:00'),
    (1000000, '0:01'),
    (59000000, '0:59'),
    (60000000, '1:00'),
    (61000000, '1:01'),
    (600000000, '10:00'),
    (3599000000, '59:59'),
    (3600000000, '1:00:00'),
    (3661000000, '1:01:01'),
    (36000000000, '10:00:00'),
]


@pytest.mark.parametrize('micros,expected', DURATIONS)
async def test_duration_of_position(
    micros, expected, metadata_test, format_player
):
    format_player.playback_status = 'Paused'  # a playing position advances
    format_player.position = micros
    await format_player.ping()
    metadata_test.add('{{duration(position)}}', expected)

    await metadata_test.run()


async def test_duration_of_length(metadata_test):
    # mpris:length is 100000 us
    metadata_test.add('{{duration(mpris:length)}}', '0:00')

    await metadata_test.run()


async def test_duration_of_number_literal(metadata_test):
    metadata_test.add('{{duration(125000000)}}', '2:05')
    metadata_test.add('{{duration(3 * 60 * 1000000)}}', '3:00')

    await metadata_test.run()


async def test_duration_missing_value_is_empty(metadata_test):
    metadata_test.add('[{{duration(xesam:missing)}}]', '[]')

    await metadata_test.run()


async def test_duration_rejects_strings(metadata_test):
    metadata_test.add('{{duration(title)}}', '', ret=1)
    metadata_test.add('{{duration("abc")}}', '', ret=1)

    await metadata_test.run()


async def test_duration_wrong_argument_count(metadata_test):
    metadata_test.add('{{duration(position, position)}}', '', ret=1)

    await metadata_test.run()
