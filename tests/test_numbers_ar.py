import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from numbers_ar import normalize


class T(unittest.TestCase):
    def test_cases(self):
        cases = {
            "الإيرادات خمسمية ألف جنيه": "الإيرادات 500 ألف جنيه",
            "ثلاثمائة وخمسون ألف": "350 ألف",
            "تلتمية ألف": "300 ألف",
            "مية وخمسين": "150",
            "عشرين في المية": "20 في المية",
            "اتنين مليون": "2 مليون",
            "الضريبة اربعتاشر في المية": "الضريبة 14 في المية",
            "تلات حاجات مهمة": "تلات حاجات مهمة",       # لا تتحول
            "واحد منهم": "واحد منهم",                     # لا تتحول
            "المصروفات ميتين ألف.": "المصروفات 200 ألف.",
            "500 ألف": "500 ألف",
        }
        for src, want in cases.items():
            self.assertEqual(normalize(src), want, src)


if __name__ == "__main__":
    unittest.main()
