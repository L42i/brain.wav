import argparse
import json
from pathlib import Path
from collections import OrderedDict
import math
import time
import socket
import struct
import pygame
# Schematic 53-node layout. Replace positions and group assignments with
# the actual NeuroMark component metadata for anatomical accuracy.
GROUPS = [
    ("SC", "Subcortical", (235, 91, 101), 5),
    ("AUD", "Auditory", (255, 164, 75), 2),
    ("SM", "Sensorimotor", (245, 214, 85), 9),
    ("VIS", "Visual", (88, 206, 138), 9),
    ("CC", "Cognitive Control", (90, 161, 250), 17),
    ("DM", "Default Mode", (175, 120, 242), 7),
    ("CB", "Cerebellar", (241, 128, 187), 4),
]  # 53 total; group sizes are illustrative until verified.
# Patch-bay configuration. Change these lists as the sound engine evolves.
PATCH_INPUTS = [
    ("x", "X"), ("y", "Y"), ("z", "Z"), ("time", "Time"),
    ("ic1", "IC 1"), ("ic2", "IC 2"), ("ic3", "IC 3"), ("mean", "Mean"),
]
PATCH_OUTPUTS = [
    ("frequency", "Frequency"), ("amplitude", "Amplitude"),
    ("grainSize", "Grain size"), ("grainDensity", "Grain density"),
    ("filterCutoff", "Filter cutoff"), ("azimuth", "Azimuth"),
    ("elevation", "Elevation"), ("distance", "Distance"),
    ("reverb", "Reverb send"),
]


class OSCTransport:
    """Minimal OSC-over-UDP sender (no third-party OSC dependency)."""

    def __init__(self, host="127.0.0.1", port=57120):
        self.set_destination(host, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def get_destination(self):
        return self.host, self.port

    def set_destination(self, host, port):
        port = int(port)
        if not host or not 1 <= port <= 65535:
            raise ValueError("Invalid OSC destination")
        self.host, self.port = host, port

    @staticmethod
    def _string(value):
        raw = value.encode("utf-8") + b"\0"
        return raw + b"\0" * ((-len(raw)) % 4)

    def send_message(self, address, value):
        if not address.startswith("/"):
            raise ValueError("OSC address must begin with /")
        packet = self._string(address) + self._string(",f") + struct.pack(">f", float(value))
        self.socket.sendto(packet, (self.host, self.port))

    def close(self):
        self.socket.close()


class InputBox:
    def __init__(self, rect, text, numeric=False):
        self.rect = pygame.Rect(rect)
        self.text, self.numeric, self.active = str(text), numeric, False
        self._text_key = None
        self._text_surface = None
    def event(self, e):
        if e.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(e.pos)
        elif e.type == pygame.KEYDOWN and self.active:
            if e.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif e.key in (pygame.K_RETURN, pygame.K_TAB):
                self.active = False
            elif e.unicode.isdigit() if self.numeric else (e.unicode.isalnum() or e.unicode in ".-_:"):
                self.text += e.unicode
    def draw(self, surface, font):
        pygame.draw.rect(surface, (15, 23, 40), self.rect, border_radius=5)
        pygame.draw.rect(surface, (115, 194, 255) if self.active else (71, 93, 130), self.rect, 2, border_radius=5)
        key = (font, self.text)
        if key != self._text_key:
            self._text_surface = font.render(self.text, True, (234, 240, 250))
            self._text_key = key
        surface.blit(self._text_surface, (self.rect.x + 7, self.rect.y + 7))
class Viz:
    def __init__(self, supercollider=None, icst=None):
        pygame.display.init()
        pygame.font.init()
        self.base_size = (1900, 900)
        self.window = pygame.display.set_mode(self.base_size, pygame.RESIZABLE)
        self.screen = pygame.Surface(self.base_size).convert()
        self._label_cache = OrderedDict()
        self._brain_layer = pygame.Surface(self.base_size).convert()
        self._orientation_overlay = pygame.Surface(self.base_size, pygame.SRCALPHA)
        self._patch_overlay = pygame.Surface((475, 820), pygame.SRCALPHA)
        self._brain_camera = None
        self._projection_angles = None
        self.viewport = pygame.Rect(0, 0, *self.base_size)
        self._resize_viewport()
        pygame.display.set_caption("Brain.wav | 3D Navigation")
        self.font = pygame.font.SysFont("Arial", 19)
        self.small = pygame.font.SysFont("Arial", 15)
        self.title = pygame.font.SysFont("Arial", 25, bold=True)
        self.supercollider = supercollider if supercollider is not None else OSCTransport()
        self._owns_sc_transport = supercollider is None
        self.icst = icst
        self.running, self.dragging = True, False
        self.mouse_virtual = (0, 0)
        self.yaw, self.pitch, self.zoom = -0.55, 0.3, 1.0
        self.history, self.trail = [], []
        self.datasets = None
        self.selected_source = 0
        self.show_groups = [True] * 7
        self.status = "Drag brain to rotate | Scroll to zoom | R to reset"
        self.patch_routes = {}  # output ID -> input ID; at most one per output
        self.patch_values = {}  # latest normalized values for routed outputs
        self.patch_file = Path(__file__).with_name("brainwav_patch.json")
        self.patch_message = "Click a cell to assign an input"
        self.patch_grid = pygame.Rect(1515, 195, 344, 9 * 49)
        self.patch_cell_width = self.patch_grid.width / len(PATCH_INPUTS)
        self.nodes = []
        # Deterministic illustrative positions, arranged throughout an ellipsoid.
        for group, (_, _, _, count) in enumerate(GROUPS):
            for j in range(count):
                k = len(self.nodes)
                a = k * 2.399963229728653
                z = 1 - 2 * (k + .5) / 53
                r = math.sqrt(max(0, 1 - z * z))
                depth = .35 + .52 * ((k * 7 % 17) / 16)
                self.nodes.append(((.88 * r * math.cos(a) * depth,
                                    .73 * r * math.sin(a) * depth,
                                    .78 * z * depth), group))
        cip, cp = self.supercollider.get_destination()
        iip, ip = icst.get_destination() if icst else ("127.0.0.1", 6668)
        self.boxes = [
            InputBox((1140, 128, 205, 34), cip),
            InputBox((1140, 170, 92, 34), cp, True),
            InputBox((1140, 278, 205, 34), iip),
            InputBox((1140, 320, 92, 34), ip, True),
        ]
        self.buttons = [pygame.Rect(1240, 170, 105, 34), pygame.Rect(1240, 320, 105, 34)]
        self.synth_id_box = InputBox((1535, 795, 65, 32), "1", True)
        self._last_osc = {}
        self.osc_interval = 1 / 30  # At most 30 sends/second per parameter.
        self._last_osc_time = 0.0
    def _resize_viewport(self):
        width, height = self.window.get_size()
        scale = min(width / self.base_size[0], height / self.base_size[1])
        w = max(1, round(self.base_size[0] * scale))
        h = max(1, round(self.base_size[1] * scale))
        self.viewport = pygame.Rect((width - w) // 2, (height - h) // 2, w, h)
        self._scaled_frame = pygame.Surface((w, h)).convert()

    def _virtual_pos(self, point):
        x = (point[0] - self.viewport.x) * self.base_size[0] / self.viewport.width
        y = (point[1] - self.viewport.y) * self.base_size[1] / self.viewport.height
        return (int(x), int(y))

    def _display_frame(self):
        # Composite the patch bay LAST, after all navigator/graph rendering.
        self.draw_patch_bay()
        self.window.fill((7, 12, 24))
        if self.viewport.size == self.base_size:
            frame = self.screen
        else:
            pygame.transform.smoothscale(self.screen, self.viewport.size, self._scaled_frame)
            frame = self._scaled_frame
        self.window.blit(frame, self.viewport.topleft)
        pygame.display.flip()

    def set_data(self, hc, sz):
        """Optional: provide complete timecourses for a real full-length graph."""
        self.datasets = (hc, sz)
    def project(self, xyz):
        x, y, z = xyz
        angles = (self.yaw, self.pitch)
        if angles != self._projection_angles:
            self._projection_angles = angles
            self._rotation = (math.cos(self.yaw), math.sin(self.yaw),
                              math.cos(self.pitch), math.sin(self.pitch))
        cy, sy, cp, sp = self._rotation
        xr, yr = cy*x - sy*y, sy*x + cy*y
        zr, depth = cp*z - sp*yr, sp*z + cp*yr
        perspective = 3.6 / max(1.0, 3.6 - depth)
        s = 285 * self.zoom * perspective
        return (int(575 + xr*s), int(390 - zr*s), perspective, depth)
    def label(self, text, x, y, color=(213, 223, 241), font=None):
        key = (font or self.small, str(text), tuple(color))
        rendered = self._label_cache.get(key)
        if rendered is None:
            rendered = key[0].render(key[1], True, color)
            self._label_cache[key] = rendered
            if len(self._label_cache) > 256:
                self._label_cache.popitem(last=False)
        else:
            self._label_cache.move_to_end(key)
        self.screen.blit(rendered, (int(x), int(y)))
    def events(self):
        for original in pygame.event.get():
            if original.type == pygame.VIDEORESIZE:
                self._resize_viewport()
                continue
            e = original
            if hasattr(original, "pos"):
                mapped = self._virtual_pos(original.pos)
                self.mouse_virtual = mapped
                attrs = dict(original.dict)
                attrs["pos"] = mapped
                if original.type == pygame.MOUSEMOTION:
                    attrs["rel"] = (
                        original.rel[0] * self.base_size[0] / self.viewport.width,
                        original.rel[1] * self.base_size[1] / self.viewport.height,
                    )
                e = pygame.event.Event(original.type, attrs)
            if e.type == pygame.QUIT:
                self.running = False
            for box in (*self.boxes, self.synth_id_box):
                box.event(e)
            if e.type == pygame.MOUSEBUTTONDOWN:
                if e.button == 1:
                    if 230 < e.pos[0] < 960 and 85 < e.pos[1] < 655:
                        self.dragging = True
                    for i, rect in enumerate(self.buttons):
                        if rect.collidepoint(e.pos):
                            target = (self.supercollider, self.icst)[i]
                            try:
                                host = self.boxes[2*i].text.strip()
                                port = int(self.boxes[2*i+1].text)
                                if not host or not 1 <= port <= 65535:
                                    raise ValueError("Invalid host or port")
                                if target:
                                    target.set_destination(host, port)
                                    self.status = f"{'SuperCollider' if i == 0 else 'ICST'} destination updated"
                                else:
                                    self.status = "Demo mode: destination not connected"
                            except Exception as err:
                                self.status = f"OSC error: {err}"
                    for i in range(7):
                        if pygame.Rect(1010, 680+i*27, 320, 23).collidepoint(e.pos):
                            self.show_groups[i] = not self.show_groups[i]
                    self.patch_click(e.pos)
                if e.button == 4:
                    self.zoom = min(2.3, self.zoom * 1.1)
                if e.button == 5:
                    self.zoom = max(.5, self.zoom / 1.1)
            if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                self.dragging = False
            if e.type == pygame.MOUSEMOTION and self.dragging:
                self.yaw -= e.rel[0] * .009
                self.pitch = max(-1.4, min(1.4, self.pitch + e.rel[1] * .009))
            if e.type == pygame.MOUSEWHEEL:
                self.zoom = max(.5, min(2.3, self.zoom * (1.1 ** e.y)))
            if e.type == pygame.KEYDOWN and e.key == pygame.K_r and not any(b.active for b in (*self.boxes, self.synth_id_box)):
                self.yaw, self.pitch, self.zoom = -.55, .3, 1.0
    def draw_brain(self):
        # Ellipsoid wireframe: the same 3D geometry rotates with the camera.
        for lat in range(-75, 90, 15):
            a = math.radians(lat)
            pts = [self.project((.92*math.cos(a)*math.cos(math.radians(t)),
                                 .76*math.cos(a)*math.sin(math.radians(t)),
                                 .82*math.sin(a)))[:2] for t in range(0, 361, 8)]
            pygame.draw.lines(self.screen, (45, 70, 105), False, pts, 1)
        for lon in range(0, 180, 15):
            a = math.radians(lon)
            pts = [self.project((.92*math.cos(math.radians(t))*math.cos(a),
                                 .76*math.cos(math.radians(t))*math.sin(a),
                                 .82*math.sin(math.radians(t))))[:2] for t in range(-90, 91, 5)]
            pygame.draw.lines(self.screen, (38, 61, 95), False, pts, 1)
        for name, xyz in [("FRONT", (0, -1.15, 0)), ("BACK", (0, 1.15, 0)),
                          ("LEFT", (-1.15, 0, 0)), ("RIGHT", (1.15, 0, 0)),
                          ("TOP", (0, 0, 1.13))]:
            x, y, _, _ = self.project(xyz)
            self.label(name, x-14, y-10, (150, 172, 198))
        p1, p2 = self.project((0, -.8, 0)), self.project((0, -1.12, 0))
        pygame.draw.line(self.screen, (180, 195, 215), p1[:2], p2[:2], 3)
    def draw_orientation_features(self):
        """Schematic translucent nose and ears attached to rotating brain."""
        overlay = self._orientation_overlay
        overlay.fill((0, 0, 0, 0))
        # A simple translucent triangle pointing toward the front (-Y).
        triangle = [(-.17, -.79, .02), (.17, -.79, .02), (0, -1.30, -.08)]
        points = [self.project(p)[:2] for p in triangle]
        pygame.draw.polygon(overlay, (206, 221, 239, 90), points)
        pygame.draw.lines(overlay, (230, 241, 255, 165), True, points, 2)
        for side in (-1, 1):
            center = (side * 1.00, 0, -.04)
            outline = []
            for i in range(33):
                a = 2 * math.pi * i / 32
                outline.append(self.project((
                    center[0] + side * .12 * math.cos(a),
                    center[1] + .18 * math.sin(a),
                    center[2] + .22 * math.cos(a),
                ))[:2])
            pygame.draw.polygon(overlay, (192, 211, 231, 65), outline)
            pygame.draw.lines(overlay, (224, 235, 249, 150), True, outline, 2)
        self.screen.blit(overlay, (0, 0))

    def draw_brain_layer(self):
        """Rebuild fixed brain features only when the camera changes."""
        camera = (self.yaw, self.pitch, self.zoom)
        if camera != self._brain_camera:
            screen = self.screen
            self._brain_layer.fill((7, 12, 24))
            self.screen = self._brain_layer
            try:
                self.label("Brain.wav  /  INTERACTIVE 3D NAVIGATION",
                           40, 20, (236, 242, 255), self.title)
                self.draw_brain()
                self.draw_orientation_features()
            finally:
                self.screen = screen
            self._brain_camera = camera
        self.screen.blit(self._brain_layer, (0, 0))

    def draw_nodes(self, row, pos):
        objects = []
        for i, (xyz, group) in enumerate(self.nodes):
            if not self.show_groups[group]:
                continue
            x, y, scale, depth = self.project(xyz)
            try:
                value = float(row[i]) if row is not None and i < len(row) else 0
            except (TypeError, ValueError):
                value = 0
            radius = max(3, int((4 + 4*min(1, abs(value))) * scale))
            objects.append((depth, "node", x, y, radius, group, i, value))
        x, y, scale, depth = self.project(pos)
        objects.append((depth, "listener", x, y, max(7, int(12*scale)), -1, -1, 0))
        # Draw farthest objects first, so nearby ones appear in front.
        mouse = self.mouse_virtual
        hover = None
        for _, kind, x, y, r, group, i, value in sorted(objects):
            if kind == "listener":
                pygame.draw.circle(self.screen, (235, 241, 247), (x, y), r+7, 2)
                pygame.draw.circle(self.screen, (191, 201, 213), (x, y), r)
                self.label("LISTENER", x+r+9, y-10, (224, 232, 241))
            else:
                color = GROUPS[group][2]
                pygame.draw.circle(self.screen, color, (x, y), r)
                pygame.draw.circle(self.screen, (225, 238, 250), (x, y), r+2, 1)
                if (mouse[0]-x)**2 + (mouse[1]-y)**2 <= (r+5)**2:
                    hover = (x, y, i, group, value)
        if hover:
            x, y, i, group, value = hover
            self.label(f"IC {i+1:02d} | {GROUPS[group][1]} | {value:+.3f}",
                       min(x+16, 980), max(75, y-25), (255, 255, 255))
    def graph(self, row, t, is_hc):
        rect = pygame.Rect(55, 710, 920, 130)
        pygame.draw.rect(self.screen, (16, 25, 42), rect, border_radius=8)
        pygame.draw.rect(self.screen, (65, 88, 124), rect, 1, border_radius=8)
        data = None
        if self.datasets:
            data = self.datasets[0 if is_hc else 1]
        if data is not None and len(data) > 1:
            vals = []
            for r in data:
                try:
                    vals.append(float(r[self.selected_source]))
                except (IndexError, TypeError, ValueError):
                    vals.append(0.0)
            caption = f"FULL DATASET TIMECOURSE | IC {self.selected_source+1:02d}"
        else:
            try:
                self.history.append(float(row[self.selected_source]))
                self.history = self.history[-400:]
            except (IndexError, TypeError, ValueError):
                pass
            vals = self.history
            caption = f"RECENT ACTIVITY (NOT FULL TIMELINE) | IC {self.selected_source+1:02d}"
        self.label(caption, 60, 676)
        if len(vals) > 1:
            lo, hi = min(vals), max(vals)
            span = hi-lo if hi != lo else 1.0
            pts = [(int(rect.x+12+i/(len(vals)-1)*(rect.width-24)),
                    int(rect.bottom-17-(v-lo)/span*(rect.height-35)))
                   for i, v in enumerate(vals)]
            pygame.draw.lines(self.screen, (90, 209, 235), False, pts, 2)
        # Playhead always represents dataset time, never history time.
        px = int(rect.x+12+t*(rect.width-24))
        pygame.draw.line(self.screen, (255, 206, 91), (px, rect.y+5), (px, rect.bottom-5), 2)
        for i in range(5):
            xx = rect.x+12+i/4*(rect.width-24)
            self.label(f"{i*25}%", xx-12, 851, (150, 173, 200))
        self.label(f"Selected time: {t*100:.1f}%", 705, 676, (255, 213, 105))
    def side_panel(self, pos, row, is_hc):
        pygame.draw.rect(self.screen, (14, 22, 37), (992, 45, 380, 600), border_radius=10)
        self.label("OSC DESTINATIONS", 1015, 62, font=self.font)
        self.label("SuperCollider IP", 1015, 135)
        self.label("Port", 1015, 179)
        self.label("ICST IP", 1015, 285)
        self.label("Port", 1015, 329)
        for b in self.boxes:
            b.draw(self.screen, self.small)
        for rect in self.buttons:
            pygame.draw.rect(self.screen, (53, 80, 120), rect, border_radius=5)
            self.label("Apply", rect.x+28, rect.y+8)
        self.label(self.status[:48], 1015, 370, (141, 203, 166))
        self.label("POSITION / DATA", 1015, 412, font=self.font)
        self.label("CONTROL" if is_hc else "SCHIZOPHRENIA", 1015, 447, (255, 215, 116))
        for i, v in enumerate(pos):
            self.label(f"{'XYZ'[i]}: {v:+.3f}", 1015, 478+i*26)
        self.label(f"Sources in row: {len(row) if row is not None else 0}", 1015, 571)
        self.label("Schematic locations until XYZ metadata", 1015, 603, (153, 173, 198))
        self.label("NETWORKS  (click to show/hide)", 1015, 656, font=self.font)
        for i, (short, name, color, count) in enumerate(GROUPS):
            y = 681+i*27
            pygame.draw.circle(self.screen, color if self.show_groups[i] else (75, 75, 85), (1021, y+9), 7)
            self.label(f"{short}  {name} ({count})", 1037, y,
                       (217, 226, 242) if self.show_groups[i] else (102, 114, 132))
    def patch_click(self, point):
        """Handle matrix toggles and preset buttons in virtual coordinates."""
        x, y = point
        if self.patch_grid.collidepoint(point):
            column = min(len(PATCH_INPUTS) - 1, int((x - self.patch_grid.x) / self.patch_cell_width))
            row = min(len(PATCH_OUTPUTS) - 1, int((y - self.patch_grid.y) / 49))
            output, input_id = PATCH_OUTPUTS[row][0], PATCH_INPUTS[column][0]
            if self.patch_routes.get(output) == input_id:
                del self.patch_routes[output]
            else:
                self.patch_routes[output] = input_id
            self.patch_message = f"{PATCH_OUTPUTS[row][1]}: {self.patch_routes.get(output, 'unmapped')}"
        elif pygame.Rect(1450, 745, 126, 36).collidepoint(point):
            try:
                self.patch_file.write_text(json.dumps(self.patch_routes, indent=2))
                self.patch_message = "Preset saved"
            except OSError as exc:
                self.patch_message = f"Save failed: {exc}"
        elif pygame.Rect(1590, 745, 126, 36).collidepoint(point):
            try:
                loaded = json.loads(self.patch_file.read_text())
                valid_inputs = {item[0] for item in PATCH_INPUTS}
                valid_outputs = {item[0] for item in PATCH_OUTPUTS}
                self.patch_routes = {k: v for k, v in loaded.items()
                                     if k in valid_outputs and v in valid_inputs}
                self.patch_message = "Preset loaded"
            except (OSError, ValueError, AttributeError) as exc:
                self.patch_message = f"Load failed: {exc}"
        elif pygame.Rect(1730, 745, 126, 36).collidepoint(point):
            self.patch_routes.clear()
            self.patch_message = "Mappings cleared"

    def mapped_audio_values(self, pos, row, time_axis):
        """Return normalized 0..1 values for the currently assigned outputs.

        This is a routing interface, not an OSC sender. Connect the returned
        dictionary to the SuperCollider OSC transport.
        """
        def bipolar(value):
            return max(0.0, min(1.0, (float(value) + 1.0) / 2.0))

        def component(index):
            try:
                return bipolar(row[index])
            except (IndexError, TypeError, ValueError):
                return 0.5

        values = {"x": bipolar(pos[0]), "y": bipolar(pos[1]),
                  "z": bipolar(pos[2]), "time": bipolar(time_axis),
                  "ic1": component(0), "ic2": component(1),
                  "ic3": component(2)}
        try:
            values["mean"] = bipolar(sum(float(v) for v in row) / len(row)) if len(row) else 0.5
        except (TypeError, ValueError, ZeroDivisionError):
            values["mean"] = 0.5
        self.patch_values = {output: values[source]
                             for output, source in self.patch_routes.items()}
        return self.patch_values.copy()

    def send_patch_osc(self):
        """Send normalized mapped values as /<synth_id>/<parameter> float."""
        if not self.patch_values:
            self._last_osc.clear()
            return
        try:
            synth_id = int(self.synth_id_box.text)
            if synth_id < 1:
                raise ValueError("Synth ID must be positive")
        except ValueError:
            self.patch_message = "Invalid synth ID"
            return
        now = time.monotonic()
        if now - self._last_osc_time < self.osc_interval:
            return
        self._last_osc_time = now
        for parameter, value in self.patch_values.items():
            address = f"/{synth_id}/{parameter}"
            try:
                # Resend periodically even when unchanged, to refresh receiver state.
                self.supercollider.send_message(address, value)
                self._last_osc[address] = value
            except (OSError, ValueError, AttributeError) as exc:
                self.patch_message = f"SuperCollider OSC error: {exc}"
                break

    def draw_patch_bay(self):
        """Draw a compact input-column / audio-output-row routing matrix."""
        panel = pygame.Rect(1400, 25, 475, 820)
        pygame.draw.rect(self.screen, (15, 23, 37), panel, border_radius=12)
        pygame.draw.rect(self.screen, (51, 70, 96), panel, 1, border_radius=12)
        self.label("AUDIO PATCH BAY", 1425, 48, font=self.title)
        self.label("Inputs across  /  Auditory outputs down", 1425, 88)
        self.label("Click to map; click again to unmap", 1425, 111, (150, 172, 198))
        self.label("One input per output; inputs can be reused", 1425, 134, (150, 172, 198))
        for column, (_, name) in enumerate(PATCH_INPUTS):
            x = self.patch_grid.x + int((column + 0.5) * self.patch_cell_width)
            text = self.small.render(name, True, (159, 199, 244) if column < 4 else (244, 178, 121))
            self.screen.blit(text, (x - text.get_width() // 2, 171))
        for index, (output, name) in enumerate(PATCH_OUTPUTS):
            y = self.patch_grid.y + index * 49
            self.label(name, 1423, y + 15)
            for column, (source, _) in enumerate(PATCH_INPUTS):
                rect = pygame.Rect(round(self.patch_grid.x + column * self.patch_cell_width) + 3,
                                   y + 4, round(self.patch_cell_width) - 6, 40)
                active = self.patch_routes.get(output) == source
                color = (59, 116, 178) if column < 4 else (168, 96, 49)
                pygame.draw.rect(self.screen, color if active else (28, 39, 56), rect, border_radius=4)
                pygame.draw.rect(self.screen, (77, 101, 133), rect, 1, border_radius=4)
                if active:
                    pygame.draw.circle(self.screen, (240, 247, 255), rect.center, 5)
                else:
                    pygame.draw.circle(self.screen, (72, 85, 103), rect.center, 2)
        self.label(f"{len(self.patch_routes)} / {len(PATCH_OUTPUTS)} outputs mapped", 1425, 670)
        self.label(self.patch_message[:52], 1425, 701, (150, 203, 173))
        for x, title in [(1450, "Save"), (1590, "Load"), (1730, "Clear")]:
            rect = pygame.Rect(x, 745, 126, 36)
            pygame.draw.rect(self.screen, (45, 66, 94), rect, border_radius=5)
            self.label(title, x + 40, 755)
        self.label("Synth ID", 1425, 801, (147, 167, 193))
        self.synth_id_box.draw(self.screen, self.small)
        self.label("OSC: /id/parameter value", 1620, 801, (147, 167, 193))

    def update(self, pos, row=None, time_axis=0, is_hc=True, keyboard_test=False):
        self.events()
        if not self.running:
            return
        t = max(0.0, min(1.0, (float(time_axis)+1)/2))
        self.screen.fill((7, 12, 24))
        self.draw_brain_layer()
        self.draw_nodes(row, pos)
        self.graph(row, t, is_hc)
        self.side_panel(pos, row, is_hc)
        self.mapped_audio_values(pos, row, time_axis)
        self.send_patch_osc()
        if keyboard_test:
            self.label("TEST | W/S front/back  A/D left/right  Q/E down/up", 55, 858, (196, 216, 235))
            self.label("J/L time  H dataset  Shift fast  Home reset  Esc quit", 55, 878, (196, 216, 235))
        self._display_frame()
    def close(self):
        self.running = False
        if self._owns_sc_transport:
            self.supercollider.close()
        pygame.display.quit()
def run_keyboard_test():
    """Standalone keyboard-controlled demo; no joystick, OSC, or data files needed."""
    viz = Viz()
    viz.status = "TEST: WASD move | Q/E height | J/L time"
    clock = pygame.time.Clock()
    position = [0.0, 0.0, 0.0]
    time_axis = 0.0  # Normalized -1..1, like the real controller.
    is_hc = True
    elapsed = 0.0
    previous_h = False
    previous_home = False
    while viz.running:
        dt = min(clock.tick(60) / 1000.0, 0.05)
        # Update handles window close, mouse rotation, zoom and text boxes.
        # Don't use keyboard shortcuts while editing an OSC destination.
        keys = pygame.key.get_pressed()
        if not any(box.active for box in (*viz.boxes, viz.synth_id_box)):
            speed = 0.65 * (2.0 if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT] else 1.0)
            position[0] += speed * dt * (int(keys[pygame.K_d]) - int(keys[pygame.K_a]))
            position[1] += speed * dt * (int(keys[pygame.K_s]) - int(keys[pygame.K_w]))
            position[2] += speed * dt * (int(keys[pygame.K_e]) - int(keys[pygame.K_q]))
            position = [max(-1.0, min(1.0, x)) for x in position]
            time_axis += dt * .55 * (int(keys[pygame.K_l]) - int(keys[pygame.K_j]))
            time_axis = max(-1.0, min(1.0, time_axis))
            if keys[pygame.K_h] and not previous_h:
                is_hc = not is_hc
            if keys[pygame.K_HOME] and not previous_home:
                position = [0.0, 0.0, 0.0]
                time_axis = 0.0
            previous_h = bool(keys[pygame.K_h])
            previous_home = bool(keys[pygame.K_HOME])
            if keys[pygame.K_ESCAPE]:
                viz.running = False
        elapsed += dt
        row = [math.sin(elapsed * (.5 + (i % 7) * .1) + i * .7 + time_axis * math.pi)
               for i in range(53)]
        viz.update(position, row, time_axis, is_hc, keyboard_test=True)
    viz.close()


def run_automatic_demo():
    """Original moving demo, with no joystick required."""
    viz = Viz()
    start = time.monotonic()
    clock = pygame.time.Clock()
    while viz.running:
        t = time.monotonic() - start
        pos = [.65 * math.sin(t * .42),
               .56 * math.cos(t * .31),
               .54 * math.sin(t * .58)]
        row = [math.sin(t * (.5 + (i % 7) * .1) + i * .7)
               for i in range(53)]
        viz.update(pos, row, math.sin(t * .13), int(t / 12) % 2 == 0)
        clock.tick(30)
    viz.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Brain.wav 3D visualization")
    parser.add_argument("--test", action="store_true", help="Keyboard test with no joystick")
    args = parser.parse_args()
    if args.test:
        run_keyboard_test()
    else:
        run_automatic_demo()
