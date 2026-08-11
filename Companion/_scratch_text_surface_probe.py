"""Read-only capture of live text/menu sources for accessibility research."""
import dolphin_memory_engine as dme

from battle_narrator.memory import MemoryReader
from battle_narrator.message_render import MessageRenderer
from battle_narrator.menus import WindowListWalker
from battle_narrator.profile import XD_US_REV0
from battle_narrator.runtime_messages import RuntimeMessageCatalog
from battle_narrator.tasks import GSmsgTaskArray


dme.hook()
if not dme.is_hooked():
    raise SystemExit("Dolphin is not readable.")

p = XD_US_REV0
memory = MemoryReader(dme, p)
catalog = RuntimeMessageCatalog(memory, p)
renderer = MessageRenderer(memory, p, catalog)

print("CONTINUE TEMPLATES")
for message_id in range(230, 239):
    rendering = renderer.render(message_id)
    print(
        f"id={message_id} catalog={catalog.text(message_id)!r} "
        f"rendered={rendering.text!r} opcodes={rendering.opcodes!r} "
        f"unresolved={rendering.unresolved!r}"
    )

print("WINDOWS")
for node in WindowListWalker(memory, p).walk():
    allocation = memory.u32(node.address + p.window_alloc_offset, "allocation")
    base = memory.u16(node.address + p.window_cursor_base_offset, "cursor base")
    cursor = memory.u16(node.address + p.window_cursor_offset, "cursor")
    print(
        f"id={node.menu_id} address=0x{node.address:08X} "
        f"allocation=0x{allocation:08X} cursor={base}+{cursor}"
    )
    if p.mem1_start <= allocation < p.mem1_end:
        values = []
        for index in range(12):
            value = memory.u32(allocation + index * 4, "allocation value")
            text = catalog.text(value)
            values.append(f"{index}:{value}(text={text!r})")
        print("  allocation words: " + ", ".join(values))

print("GSMSG TASKS")
tasks = GSmsgTaskArray(memory, p)
tasks.resolve()
for task in tasks.snapshots():
    if task.packed_id:
        message_id = task.packed_id & 0xFFFFF
        print(
            f"address=0x{task.address:08X} state={task.state} "
            f"packed={task.packed_id} id={message_id} "
            f"text={catalog.text(task.packed_id)!r}"
        )
