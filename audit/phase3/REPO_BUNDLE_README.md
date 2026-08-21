# `repo.bundle` — хуваагдсан

Git-ийн бүх түүхийн bundle нь **105.35 MB** бөгөөд GitHub-ийн нэг файлын **100 MB** хязгаараас
хэтэрсэн тул хоёр хэсэгт хуваагдсан.

Нийлүүлэх:

```
cat repo.bundle.partaa repo.bundle.partab > repo.bundle
shasum -a 256 -c repo.bundle.sha256
git clone repo.bundle solana-flow-research
```

Хэмжээ ийм том болсон шалтгаан: өмнөх үе шатуудын bundle нь git-д track хийгдсэн тул шинэ
bundle тэднийг агуулна — `audit/phase1/repo.bundle` 13.7 MB, `audit/phase2/repo.bundle` 39 MB,
`data/cache/bootstrap_cell.npz` 24 MB, `audit_phase1.zip` 14 MB. Үе шат бүрт хуримтлагдана.
**Тэмдэглэв, засаагүй.**
