"""给项目配置品牌实体，并按新口径回填历史样本的 brand_identified。

用法（backend 目录下，先设 PYTHONPATH）：
    $env:PYTHONPATH = "C:\\...\\geo-system\\backend"
    .\\.venv\\Scripts\\python.exe scripts\\setup_brand_profile.py --project-code gz-base --dry-run
    .\\.venv\\Scripts\\python.exe scripts\\setup_brand_profile.py --project-code gz-base --apply

三条硬约束（脚本不是“补数据”，是“按口径重算”）：
1. **不动 `brand_mentioned`**：它的定义与 11-16/11-17 两轮历史数据绑死，
   一旦按新别名重算，历史提及率立刻失真、跨期不可比。
2. 只回填 `brand_identified`（新字段，此前所有样本都是 NULL=未判定），
   用的是当前配置的「唯一标识」词表；词表为空则不回填，保持 NULL。
3. 不猜域名。项目没有已知官网/公众号（Q01 答案原话「未提供官方网站或公众号报名入口」），
   所以 `owned_domains` 默认留空，由人补——编一个域名会让信源占比算错。
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BrandProfile, MonitoringSample, Project
from app.services.brand_profile import build_vocabulary
from app.services.monitoring_extraction import detect_brand_identified

# 这些值来自 11-16 / 11-17 两轮 DeepSeek 真实作答与人工核对，不是占位符：
# 品牌全名与运营主体都是实测中出现过的实体名；地址/电话是 Q01 答案里给出的原文。
#
# identifiers 的取值原则：**越精确越好，宁窄不宽**。
# 「番禺节能科技园」这类园区名（以及「番山创业中心」这类写字楼名）里面驻着许多公司，
# 拿它当“唯一定位品牌的标识”会把别人的地址当成自己的品牌可识别，指标就失真了。
# 所以这里只保留精确到房号的地址、门牌号与电话。
DEFAULT_PROFILE = {
    "canonical_name": "广东省AI数字人才就业实训基地",
    "aliases": [
        "广东省AI数字人才就业实训基地",
        "广东省成才人工智能产业孵化有限公司",
        "成才",
    ],
    "identifiers": [
        "番山创业中心1号楼2区2楼",
        "番禺大道北537号",
        "13022038683",
    ],
    "owned_domains": [],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-code", required=True, help="项目 code，例如 gz-base")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正写库；不加此参数只做 dry-run 打印",
    )
    parser.add_argument(
        "--skip-backfill",
        action="store_true",
        help="只配置品牌实体，不回填历史样本的 brand_identified",
    )
    args = parser.parse_args()

    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            print(f"[abort] 项目 code={args.project_code} 不存在")
            return 2

        print(f"项目：{project.code} / {project.name}（id={project.id}）")

        profile = db.scalar(
            select(BrandProfile).where(BrandProfile.project_id == project.id)
        )
        if profile is None:
            print("品牌实体：未配置（将新建）")
        else:
            print(
                "品牌实体：已存在 → "
                f"canonical_name={profile.canonical_name!r} "
                f"aliases={profile.aliases} identifiers={profile.identifiers} "
                f"owned_domains={profile.owned_domains} is_active={profile.is_active}"
            )

        if not args.apply:
            print("\n[dry-run] 将写入：")
            for key, value in DEFAULT_PROFILE.items():
                print(f"  {key} = {value}")
            print("（加 --apply 才会真正落库）")
            return 0

        if profile is None:
            profile = BrandProfile(project_id=project.id)
            db.add(profile)
        profile.canonical_name = DEFAULT_PROFILE["canonical_name"]
        profile.aliases = DEFAULT_PROFILE["aliases"]
        profile.identifiers = DEFAULT_PROFILE["identifiers"]
        profile.owned_domains = DEFAULT_PROFILE["owned_domains"]
        profile.notes = (
            "由 scripts/setup_brand_profile.py 按 11-16/11-17 实测事实建立。"
            "aliases 只放名称类词条（命中即 brand_mentioned）；"
            "identifiers 放地址/电话（命中即 brand_identified，不影响提及率）；"
            "owned_domains 待补：项目目前没有已知官网或公众号。"
        )
        profile.is_active = True
        db.flush()
        print("品牌实体已写入。")

        vocabulary = build_vocabulary(db, project.id, project=project)
        print(f"生效词表：mention={vocabulary.mention_terms}")
        print(f"          identifier={vocabulary.identifier_terms}")
        print(f"          domains={vocabulary.owned_domains}")

        if not args.skip_backfill:
            samples = db.scalars(
                select(MonitoringSample).where(MonitoringSample.project_id == project.id)
            ).all()
            changed = 0
            for sample in samples:
                identified = detect_brand_identified(
                    sample.raw_answer, vocabulary.identifier_terms
                )
                if sample.brand_identified != identified:
                    sample.brand_identified = identified
                    changed += 1
            db.flush()
            print(
                f"回填 brand_identified：样本 {len(samples)} 条，变更 {changed} 条。"
                "（brand_mentioned 一律不动，历史提及率保持原口径）"
            )
            for sample in samples:
                if sample.brand_identified:
                    print(
                        f"  identified=True sample={sample.id} "
                        f"mentioned={sample.brand_mentioned} status={sample.status.value}"
                    )

        db.commit()
        print("已提交。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
