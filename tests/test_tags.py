import uuid

from dam.models import AssetTag, TagSource
from dam.repositories.tags import merge_auto_tags


def _row(tag_id, source, suppressed=False):
    return AssetTag(
        asset_id=uuid.uuid4(),
        tag_id=tag_id,
        firm_id=uuid.uuid4(),
        source=source,
        suppressed=suppressed,
        confidence=0.5,
    )


def test_auto_tags_never_touch_manual_rows():
    manual, suppressed, old_auto, kept_auto = (uuid.uuid4() for _ in range(4))
    new = uuid.uuid4()
    existing = [
        _row(manual, TagSource.manual),
        _row(suppressed, TagSource.manual, suppressed=True),
        _row(old_auto, TagSource.auto),
        _row(kept_auto, TagSource.auto),
    ]
    # The model proposes: the suppressed one again, the manual one, kept_auto with a new
    # confidence, and a brand new tag. old_auto is no longer proposed.
    proposed = {suppressed: 0.9, manual: 0.9, kept_auto: 0.7, new: 0.8}
    add, remove, update = merge_auto_tags(existing, proposed)
    assert add == [new]
    assert remove == [old_auto]
    assert update == {kept_auto: 0.7}
    # Neither the manual tag nor the suppression appears anywhere in the diff.
    assert manual not in add and manual not in update
    assert suppressed not in add and suppressed not in update


def test_empty_proposal_clears_auto_only():
    manual, auto = uuid.uuid4(), uuid.uuid4()
    add, remove, update = merge_auto_tags([_row(manual, TagSource.manual), _row(auto, TagSource.auto)], {})
    assert add == [] and remove == [auto] and update == {}
