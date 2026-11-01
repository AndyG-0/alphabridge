import db
from models import UserProfile
from userctx import current_user_id


def get_profile() -> UserProfile:
    s = db.session()
    uid = current_user_id()
    p = s.get(UserProfile, uid)
    if p is None:
        p = UserProfile(id=uid)
        s.add(p)
        s.commit()
    return p
