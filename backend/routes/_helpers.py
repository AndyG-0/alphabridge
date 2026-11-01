import db
from models import UserProfile


def get_profile() -> UserProfile:
    s = db.session()
    p = s.get(UserProfile, 1)
    if p is None:
        p = UserProfile(id=1)
        s.add(p)
        s.commit()
    return p
