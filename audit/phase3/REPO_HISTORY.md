# Git түүх — энэ багцад bundle БАЙХГҮЙ

`audit/phase3/repo.bundle` нь **105.35 MB** болж GitHub-ийн 100 MB хязгаараас хэтэрсэн.
Шалтгаан: өмнөх үе шатуудын bundle нь git-д track хийгдсэн тул шинэ bundle тэднийг **дотроо
агуулна** — `audit/phase1/repo.bundle` 13.7 MB, `audit/phase2/repo.bundle` 39 MB,
`data/cache/bootstrap_cell.npz` 24 MB, `audit_phase1.zip` 14 MB. Үе шат бүрт хуримтлагдана.

**Шийдвэр (судалгааны эзэн, 2026-08-21): `audit/phase3/`-аас bundle ХАСАГДАВ.**
Өмнөх bundle-ууд `audit/phase0/`, `audit/phase1/`, `audit/phase2/` дотор **хэвээр**.

Түүхийг авах гурван зам:

1. Репог өөрийг нь клон хийх — `git clone git@github.com:git-bino/solana-flow-research.git`
2. `audit/phase2/repo.bundle` — Phase 2 хүртэлх бүх түүх
3. `git_log.txt` ба `git_log_p_decisions.txt` — commit бүрийн гарчиг ба `decisions.md`-ийн
   бүтэн diff түүх, энэ багцад байгаа
