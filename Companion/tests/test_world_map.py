from battle_narrator.world_map import WorldMapReader


class Memory:
    values = {
        0x804EA6F8: 0x81000000,
        0x81000008: 0x81000100,
        0x81000130: 1,
        0x804EA700: 5,
        0x80428082: 5,
        0x804E87D4: 0x80C00000,
        0x80C00018: 54503,
    }

    def u32(self, address, _label):
        return self.values.get(address, 0)

    def u16(self, address, _label):
        return self.values.get(address, 0)


class Catalog:
    def resolve(self, message_id):
        assert message_id == 54503
        return "Agate Village", "A lush green town."


class Speech:
    def __init__(self): self.events = []
    def emit(self, _kind, text, interrupt=False): self.events.append((text, interrupt))


class Logger:
    def info(self, *_args): pass


def test_live_cursor_resolves_destination_message_and_position():
    speech = Speech()
    reader = WorldMapReader(Memory(), Catalog(), speech, Logger())
    assert reader.poll_once() is True
    assert speech.events == [
        ("Agate Village. A lush green town. Destination 2 of 5.", True)
    ]
    reader.poll_once()
    assert len(speech.events) == 1
