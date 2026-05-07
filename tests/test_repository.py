"""
Тесты UserRepository — CRUD-операции с пользователями, профилями,
свайпами и мэтчами.
"""

from datetime import date

from app.repository import UserRepository


# ─── Вспомогательная функция ─────────────────────────────────────────────────

async def _make_user_with_profile(session, telegram_id: int, display_name: str = "Тест"):
    repo = UserRepository(session)
    user, _ = await repo.get_or_create_user(telegram_id)
    profile = await repo.save_profile(user.id, display_name=display_name)
    return user, profile


# ─── Пользователи ────────────────────────────────────────────────────────────

class TestUserCRUD:
    async def test_create_user_sets_defaults(self, db_session):
        repo = UserRepository(db_session)
        user = await repo.create_user(telegram_id=12345)
        await db_session.commit()

        assert user.telegram_id == 12345
        assert user.is_active is True
        assert user.is_registered is False
        assert user.id is not None

    async def test_get_or_create_user_returns_is_new_true(self, db_session):
        repo = UserRepository(db_session)
        _, is_new = await repo.get_or_create_user(telegram_id=99001)
        assert is_new is True

    async def test_get_or_create_user_returns_existing(self, db_session):
        repo = UserRepository(db_session)
        u1, _ = await repo.get_or_create_user(telegram_id=99002)
        u2, is_new = await repo.get_or_create_user(telegram_id=99002)

        assert is_new is False
        assert u1.id == u2.id

    async def test_get_user_by_telegram_id_not_found(self, db_session):
        repo = UserRepository(db_session)
        result = await repo.get_user_by_telegram_id(telegram_id=0)
        assert result is None


# ─── Профили ─────────────────────────────────────────────────────────────────

class TestProfileCRUD:
    async def test_save_profile_creates_record(self, db_session):
        repo = UserRepository(db_session)
        user, _ = await repo.get_or_create_user(telegram_id=20001)

        profile = await repo.save_profile(
            user_id=user.id,
            display_name="Иван",
            bio="Рассказ о себе (длиннее 10 символов)",
            birth_date=date(1998, 6, 15),
            gender="male",
            city="Москва",
            interests="Спорт, Музыка",
        )

        assert profile.display_name == "Иван"
        assert profile.city == "Москва"
        assert profile.gender == "male"
        assert profile.profile_completeness > 0

    async def test_save_profile_marks_user_registered(self, db_session):
        repo = UserRepository(db_session)
        user, _ = await repo.get_or_create_user(telegram_id=20002)
        assert user.is_registered is False

        await repo.save_profile(user.id, display_name="Анна")
        await db_session.refresh(user)

        assert user.is_registered is True

    async def test_save_profile_upsert_updates_name(self, db_session):
        repo = UserRepository(db_session)
        user, _ = await repo.get_or_create_user(telegram_id=20003)

        await repo.save_profile(user.id, display_name="Старое Имя")
        updated = await repo.save_profile(user.id, display_name="Новое Имя")

        assert updated.display_name == "Новое Имя"

    async def test_get_profile_by_id_returns_profile(self, db_session):
        user, profile = await _make_user_with_profile(db_session, telegram_id=20004)
        repo = UserRepository(db_session)

        found = await repo.get_profile_by_id(profile.id)
        assert found is not None
        assert found.id == profile.id

    async def test_get_profile_by_id_not_found(self, db_session):
        repo = UserRepository(db_session)
        result = await repo.get_profile_by_id(999999)
        assert result is None

    async def test_add_photo_increments_sort_order(self, db_session):
        user, profile = await _make_user_with_profile(db_session, telegram_id=20005)
        repo = UserRepository(db_session)

        p1 = await repo.add_photo(profile.id, file_id="file_aaa")
        p2 = await repo.add_photo(profile.id, file_id="file_bbb")

        assert p1.sort_order == 1
        assert p2.sort_order == 2

    async def test_get_photos_returns_ordered(self, db_session):
        user, profile = await _make_user_with_profile(db_session, telegram_id=20006)
        repo = UserRepository(db_session)

        await repo.add_photo(profile.id, file_id="f1")
        await repo.add_photo(profile.id, file_id="f2")
        photos = await repo.get_photos(profile.id)

        assert len(photos) == 2
        assert photos[0].sort_order < photos[1].sort_order


# ─── Полнота анкеты (статический метод) ─────────────────────────────────────

class TestCompleteness:
    def test_empty_profile_is_zero(self):
        score = UserRepository._calculate_completeness(
            None, None, None, None, None, None, photo_count=0
        )
        assert score == 0

    def test_full_profile_is_100(self):
        score = UserRepository._calculate_completeness(
            display_name="Иван",
            bio="Это описание длиннее десяти символов",
            birth_date=date(1995, 1, 1),
            gender="male",
            city="Москва",
            interests="Спорт",
            photo_count=2,
        )
        assert score == 100

    def test_only_name_gives_15(self):
        score = UserRepository._calculate_completeness(
            display_name="Анна",
            bio=None, birth_date=None, gender=None, city=None, interests=None,
        )
        assert score == 15

    def test_short_bio_not_counted(self):
        score_with_short = UserRepository._calculate_completeness(
            display_name="Иван", bio="abc",
            birth_date=None, gender=None, city=None, interests=None,
        )
        score_without = UserRepository._calculate_completeness(
            display_name="Иван", bio=None,
            birth_date=None, gender=None, city=None, interests=None,
        )
        assert score_with_short == score_without  # короткое bio не засчитывается

    def test_photos_capped_at_10_points(self):
        score_many_photos = UserRepository._calculate_completeness(
            display_name="X", bio=None, birth_date=None, gender=None,
            city=None, interests=None, photo_count=10,
        )
        score_two_photos = UserRepository._calculate_completeness(
            display_name="X", bio=None, birth_date=None, gender=None,
            city=None, interests=None, photo_count=2,
        )
        assert score_many_photos == score_two_photos  # максимум 10 баллов за фото


# ─── Свайпы ──────────────────────────────────────────────────────────────────

class TestSwipes:
    async def test_record_swipe_like(self, db_session):
        user1, _ = await _make_user_with_profile(db_session, telegram_id=30001)
        user2, _ = await _make_user_with_profile(db_session, telegram_id=30002)
        repo = UserRepository(db_session)

        swipe = await repo.record_swipe(user1.id, user2.id, "like")
        await db_session.commit()

        assert swipe.action == "like"
        assert swipe.from_user_id == user1.id
        assert swipe.to_user_id == user2.id

    async def test_get_swipe_returns_none_if_not_exists(self, db_session):
        repo = UserRepository(db_session)
        result = await repo.get_swipe(from_user_id=1, to_user_id=2)
        assert result is None

    async def test_check_mutual_like_both_liked(self, db_session):
        user1, _ = await _make_user_with_profile(db_session, telegram_id=30003)
        user2, _ = await _make_user_with_profile(db_session, telegram_id=30004)
        repo = UserRepository(db_session)

        await repo.record_swipe(user1.id, user2.id, "like")
        await repo.record_swipe(user2.id, user1.id, "like")
        await db_session.commit()

        assert await repo.check_mutual_like(user1.id, user2.id) is True

    async def test_check_mutual_like_one_sided(self, db_session):
        user1, _ = await _make_user_with_profile(db_session, telegram_id=30005)
        user2, _ = await _make_user_with_profile(db_session, telegram_id=30006)
        repo = UserRepository(db_session)

        await repo.record_swipe(user1.id, user2.id, "like")
        await db_session.commit()

        assert await repo.check_mutual_like(user1.id, user2.id) is False

    async def test_check_mutual_like_pass_does_not_count(self, db_session):
        user1, _ = await _make_user_with_profile(db_session, telegram_id=30007)
        user2, _ = await _make_user_with_profile(db_session, telegram_id=30008)
        repo = UserRepository(db_session)

        await repo.record_swipe(user1.id, user2.id, "like")
        await repo.record_swipe(user2.id, user1.id, "pass")
        await db_session.commit()

        assert await repo.check_mutual_like(user1.id, user2.id) is False


# ─── Мэтчи ───────────────────────────────────────────────────────────────────

class TestMatches:
    async def test_create_match_canonical_order(self, db_session):
        user1, _ = await _make_user_with_profile(db_session, telegram_id=40001)
        user2, _ = await _make_user_with_profile(db_session, telegram_id=40002)
        repo = UserRepository(db_session)

        # Передаём в «неправильном» порядке — должен переставить
        match = await repo.create_match(user2.id, user1.id)
        await db_session.commit()

        assert match.user_a_id == min(user1.id, user2.id)
        assert match.user_b_id == max(user1.id, user2.id)

    async def test_get_match_returns_existing(self, db_session):
        user1, _ = await _make_user_with_profile(db_session, telegram_id=40003)
        user2, _ = await _make_user_with_profile(db_session, telegram_id=40004)
        repo = UserRepository(db_session)

        created = await repo.create_match(user1.id, user2.id)
        await db_session.commit()
        found = await repo.get_match(user1.id, user2.id)

        assert found is not None
        assert found.id == created.id

    async def test_get_user_matches_returns_all(self, db_session):
        user1, _ = await _make_user_with_profile(db_session, telegram_id=40005)
        user2, _ = await _make_user_with_profile(db_session, telegram_id=40006)
        user3, _ = await _make_user_with_profile(db_session, telegram_id=40007)
        repo = UserRepository(db_session)

        await repo.create_match(user1.id, user2.id)
        await repo.create_match(user1.id, user3.id)
        await db_session.commit()

        matches = await repo.get_user_matches(user1.id)
        assert len(matches) == 2

    async def test_get_partner_user_id(self, db_session):
        user1, _ = await _make_user_with_profile(db_session, telegram_id=40008)
        user2, _ = await _make_user_with_profile(db_session, telegram_id=40009)
        repo = UserRepository(db_session)

        match = await repo.create_match(user1.id, user2.id)
        await db_session.commit()

        partner_of_1 = await repo.get_partner_user_id(match, user1.id)
        partner_of_2 = await repo.get_partner_user_id(match, user2.id)

        assert partner_of_1 == user2.id
        assert partner_of_2 == user1.id
