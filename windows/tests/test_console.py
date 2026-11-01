import unittest

from aethel.views import console


@unittest.skipUnless(console.AVAILABLE, "needs pyte and pywinpty (ptyprocess off Windows)")
class ScreenTests(unittest.TestCase):
    def screen(self, cols=20, rows=10):
        replies = []
        screen = console._Screen(cols, rows, replies.append)
        return screen, console.pyte.Stream(screen), replies

    def test_shrinking_keeps_visible_text(self):
        screen, stream, _ = self.screen()
        stream.feed("one\r\ntwo\r\nthree\r\n")
        screen.resize(8, 20)
        self.assertEqual([screen.display[i].rstrip() for i in range(3)], ["one", "two", "three"])
        self.assertEqual(len(screen.history.top), 0)

    def test_shrinking_below_the_cursor_moves_lines_to_scrollback(self):
        screen, stream, _ = self.screen()
        stream.feed("\r\n".join(f"l{i}" for i in range(12)))
        screen.resize(4, 20)
        self.assertEqual([screen.display[i].rstrip() for i in range(4)], ["l8", "l9", "l10", "l11"])
        self.assertEqual(screen.cursor.y, 3)
        self.assertEqual("".join(c.data for c in screen.history.top[-1].values()).rstrip(), "l7")

    def test_cursor_position_query_is_answered(self):
        screen, stream, replies = self.screen()
        stream.feed("ab\x1b[6n")
        self.assertEqual(replies, ["\x1b[1;3R"])

    def test_bracketed_paste_mode_is_tracked(self):
        screen, stream, _ = self.screen()
        stream.feed("\x1b[?2004h")
        self.assertIn(console._BRACKETED_PASTE, screen.mode)


if __name__ == "__main__":
    unittest.main()
