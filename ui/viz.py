import pygame
import math
import time


class InputBox:
    def __init__(self, x, y, w, text, numbers=False):
        self.rect = pygame.Rect(x, y, w, 32)
        self.text = str(text)
        self.active = False
        self.numbers = numbers

    def event(self, e):
        if e.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(e.pos)

        if e.type == pygame.KEYDOWN and self.active:
            if e.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif e.key == pygame.K_RETURN:
                self.active = False
            elif (not self.numbers and (e.unicode.isalnum() or e.unicode in ".-_:")) \
                    or (self.numbers and e.unicode.isdigit()):
                self.text += e.unicode

    def draw(self, screen, font):
        color = (120, 190, 255) if self.active else (75, 95, 130)
        pygame.draw.rect(screen, (12, 17, 30), self.rect)
        pygame.draw.rect(screen, color, self.rect, 2)
        screen.blit(font.render(self.text, True, (240, 240, 245)),
                    (self.rect.x + 6, self.rect.y + 6))


class Viz:
    def __init__(self, chuck=None, icst=None):
        self.chuck, self.icst = chuck, icst

        pygame.display.init()
        # pygame.font.init()

        self.screen = pygame.display.set_mode((1400, 900))
        pygame.display.set_caption("fMRI Sonification - Brain Navigation")

        self.font = pygame.font.SysFont("Arial", 18)
        self.small = pygame.font.SysFont("Arial", 14)
        self.title = pygame.font.SysFont("Arial", 26)

        self.running = True
        self.trail = []
        self.history = []

        # Temporary source locations.
        # Replace with real anatomical XYZ coordinates when available.
        self.sources = [
            (-.45, .30, .25),
            (.40, .25, .35),
            (-.25, -.35, .10),
            (.35, -.25, -.05),
            (0, .05, .55),
            (-.10, .10, -.45)
        ]

        cip, cp = chuck.get_destination() if chuck else ("127.0.0.1", 6667)
        iip, ip = icst.get_destination() if icst else ("127.0.0.1", 6668)

        self.cip = InputBox(1140, 120, 200, cip)
        self.cp = InputBox(1140, 160, 90, cp, True)
        self.iip = InputBox(1140, 260, 200, iip)
        self.ip = InputBox(1140, 300, 90, ip, True)

        self.capply = pygame.Rect(1240, 160, 100, 32)
        self.iapply = pygame.Rect(1240, 300, 100, 32)

        self.status = "OSC ready"

    # ------------------------------------------------------------
    # 3D -> 2D
    # ------------------------------------------------------------

    def project(self, x, y, z):
        s = 255
        return (
            int(590 + (x - y) * s * .82),
            int(400 + (x + y) * s * .28 - z * s)
        )

    # ------------------------------------------------------------
    # Brain + head orientation
    # ------------------------------------------------------------

    def brain(self):
        # Latitude lines
        for lat_deg in range(-60, 61, 15):
            lat = math.radians(lat_deg)
            pts = []

            for a in range(0, 361, 8):
                t = math.radians(a)
                pts.append(self.project(
                    .88 * math.cos(lat) * math.cos(t),
                    .72 * math.cos(lat) * math.sin(t),
                    .78 * math.sin(lat)
                ))

            pygame.draw.lines(self.screen, (45, 65, 100), False, pts)

        # Longitude lines
        for lon_deg in range(0, 180, 15):
            lon = math.radians(lon_deg)
            pts = []

            for lat_deg in range(-90, 91, 5):
                lat = math.radians(lat_deg)
                pts.append(self.project(
                    .88 * math.cos(lat) * math.cos(lon),
                    .72 * math.cos(lat) * math.sin(lon),
                    .78 * math.sin(lat)
                ))

            pygame.draw.lines(self.screen, (38, 55, 88), False, pts)

        # Orientation
        labels = [
            ("FRONT", 0, -1, 0),
            ("BACK", 0, 1, 0),
            ("LEFT", -1, 0, 0),
            ("RIGHT", 1, 0, 0)
        ]

        for name, x, y, z in labels:
            px, py = self.project(x, y, z)
            self.screen.blit(
                self.small.render(name, True, (180, 190, 210)),
                (px, py)
            )

        # Nose/front indicator
        pygame.draw.line(
            self.screen,
            (150, 160, 180),
            self.project(0, -.7, 0),
            self.project(0, -1.05, 0),
            3
        )

    # ------------------------------------------------------------
    # Brain sources
    # ------------------------------------------------------------

    def draw_sources(self, row):
        for i, xyz in enumerate(self.sources):
            value = 0

            if row is not None and i < len(row):
                try:
                    value = float(row[i])
                except (ValueError, TypeError):
                    pass

            p = self.project(*xyz)
            radius = 5 + int(min(1, abs(value)) * 10)

            pygame.draw.circle(self.screen, (80, 190, 235), p, radius)
            pygame.draw.circle(self.screen, (190, 230, 255), p, radius + 2, 1)

            self.screen.blit(
                self.small.render(f"Source {i + 1}", True, (160, 200, 220)),
                (p[0] + radius + 3, p[1])
            )

    # ------------------------------------------------------------
    # Listener
    # ------------------------------------------------------------

    def listener(self, pos):
        p = self.project(*pos)

        self.trail.append(p)
        self.trail = self.trail[-250:]

        if len(self.trail) > 1:
            pygame.draw.lines(self.screen, (75, 145, 205), False, self.trail, 2)

        pygame.draw.circle(self.screen, (255, 255, 255), p, 18, 2)
        pygame.draw.circle(self.screen, (255, 80, 80), p, 10)
        pygame.draw.circle(self.screen, (255, 255, 255), p, 3)

        self.screen.blit(
            self.small.render("LISTENER", True, (255, 255, 255)),
            (p[0] + 22, p[1] - 7)
        )

    # ------------------------------------------------------------
    # Time/data graph
    # ------------------------------------------------------------

    def graph(self, row, t):
        rect = pygame.Rect(70, 690, 900, 155)
        pygame.draw.rect(self.screen, (14, 19, 34), rect)
        pygame.draw.rect(self.screen, (55, 70, 105), rect, 2)

        self.screen.blit(
            self.small.render("TIME / DATA - SOURCE 1", True, (210, 220, 240)),
            (70, 665)
        )

        # Add current Source 1 value
        if row:
            try:
                self.history.append(float(row[0]))
                self.history = self.history[-500:]
            except (ValueError, TypeError):
                pass

        if len(self.history) > 1:
            lo, hi = min(self.history), max(self.history)

            if hi == lo:
                hi += 1

            pts = []

            for i, v in enumerate(self.history):
                x = rect.x + i / 499 * rect.width
                y = rect.bottom - 15 - ((v - lo) / (hi - lo)) * (rect.height - 30)
                pts.append((int(x), int(y)))

            pygame.draw.lines(self.screen, (90, 205, 235), False, pts, 2)

        # Time playhead
        x = rect.x + int(rect.width * t)

        pygame.draw.line(
            self.screen,
            (255, 210, 90),
            (x, rect.y),
            (x, rect.bottom),
            2
        )

        self.screen.blit(
            self.small.render(f"{t * 100:.1f}%", True, (255, 220, 120)),
            (x + 5, rect.y + 5)
        )

    # ------------------------------------------------------------
    # Information
    # ------------------------------------------------------------

    def info(self, pos, row, t, is_hc):
        lines = [
            "LISTENER POSITION",
            f"X: {pos[0]:+.3f}",
            f"Y: {pos[1]:+.3f}",
            f"Z: {pos[2]:+.3f}",
            "",
            "CONTROL" if is_hc else "SCHIZOPHRENIA",
            f"Time: {t * 100:.1f}%"
        ]

        y = 70

        for line in lines:
            self.screen.blit(
                self.font.render(line, True, (220, 230, 245)),
                (50, y)
            )
            y += 25

        # Current source values
        if row:
            y = 430

            self.screen.blit(
                self.font.render("CURRENT DATA", True, (230, 235, 245)),
                (1010, y)
            )

            for i, value in enumerate(row[:6]):
                y += 25

                try:
                    text = f"Source {i + 1}: {float(value):+.4f}"
                except (ValueError, TypeError):
                    text = f"Source {i + 1}: {value}"

                self.screen.blit(
                    self.small.render(text, True, (150, 200, 225)),
                    (1010, y)
                )

    # ------------------------------------------------------------
    # OSC menu
    # ------------------------------------------------------------

    def osc_menu(self):
        pygame.draw.rect(self.screen, (15, 20, 35), (1090, 50, 280, 310))
        pygame.draw.rect(self.screen, (55, 70, 105), (1090, 50, 280, 310), 2)

        self.screen.blit(
            self.font.render("OSC DESTINATIONS", True, (235, 235, 245)),
            (1110, 70)
        )

        self.screen.blit(self.small.render("ChucK IP", True, (190, 200, 220)), (1110, 100))
        self.cip.draw(self.screen, self.small)
        self.cp.draw(self.screen, self.small)

        self.screen.blit(self.small.render("ICST IP", True, (190, 200, 220)), (1110, 240))
        self.iip.draw(self.screen, self.small)
        self.ip.draw(self.screen, self.small)

        for rect in (self.capply, self.iapply):
            pygame.draw.rect(self.screen, (45, 65, 100), rect)
            pygame.draw.rect(self.screen, (100, 130, 175), rect, 1)

            self.screen.blit(
                self.small.render("Apply", True, (240, 240, 245)),
                (rect.x + 28, rect.y + 7)
            )

        self.screen.blit(
            self.small.render(self.status, True, (140, 210, 170)),
            (1110, 340)
        )

    def events(self):
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.running = False

            for box in (self.cip, self.cp, self.iip, self.ip):
                box.event(e)

            if e.type == pygame.MOUSEBUTTONDOWN:

                if self.capply.collidepoint(e.pos):
                    try:
                        if self.chuck:
                            self.chuck.set_destination(
                                self.cip.text,
                                int(self.cp.text)
                            )
                        self.status = "ChucK updated"
                    except Exception as err:
                        self.status = f"Error: {err}"

                if self.iapply.collidepoint(e.pos):
                    try:
                        if self.icst:
                            self.icst.set_destination(
                                self.iip.text,
                                int(self.ip.text)
                            )
                        self.status = "ICST updated"
                    except Exception as err:
                        self.status = f"Error: {err}"

    # ------------------------------------------------------------
    # Called by main.py
    # ------------------------------------------------------------

    def update(self, pos, row=None, time_axis=0, is_hc=True):
        self.events()

        # -1...+1 controller range -> 0...1
        t = max(0, min(1, (time_axis + 1) / 2))

        self.screen.fill((6, 9, 18))

        self.screen.blit(
            self.title.render(
                "fMRI SONIFICATION / ALLOCENTRIC NAVIGATION",
                True,
                (235, 240, 250)
            ),
            (45, 18)
        )

        self.brain()
        self.draw_sources(row)
        self.listener(pos)
        self.info(pos, row, t, is_hc)
        self.graph(row, t)
        self.osc_menu()

        pygame.display.flip()

    def close(self):
        self.running = False
""" 

# ================================================================
# TEST WITHOUT CONTROLLER
# ================================================================

if __name__ == "__main__":
    viz = Viz()
    start = time.time()

    while viz.running:
        t = time.time() - start

        # Fake XYZ movement
        pos = [
            math.sin(t * .5) * .65,
            math.cos(t * .35) * .55,
            math.sin(t * .7) * .5
        ]

        # Fake source data
        row = [
            math.sin(t),
            math.sin(t * 1.3 + 1),
            math.sin(t * .7 + 2),
            math.cos(t * 1.1),
            math.sin(t * 1.7 + 3),
            math.cos(t * .6 + 1)
        ]

        # Fake time control
        time_axis = math.sin(t * .15)

        viz.update(
            pos,
            row,
            time_axis,
            True
        )

        time.sleep(.05)

    pygame.quit() """