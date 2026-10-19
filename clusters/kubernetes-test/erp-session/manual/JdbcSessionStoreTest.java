package de.metas.ui.web.session.jdbc;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.Properties;
import java.util.function.Consumer;

import javax.sql.DataSource;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.RootBeanDefinition;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.core.ResolvableType;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.session.Session;
import org.springframework.session.SessionRepository;
import org.springframework.session.config.annotation.web.http.SpringHttpSessionConfiguration;

import static org.junit.jupiter.api.Assertions.*;

// Kept outside the ERP reactor: these tests require a disposable PostgreSQL server.
class JdbcSessionStoreTest
{
	private DataSource dataSource;
	private JdbcTemplate jdbc;
	private SessionRepository<? extends Session> first;
	private SessionRepository<? extends Session> second;

	@BeforeEach
	void prepareDatabase()
	{
		final String url = System.getenv("SESSION_TEST_JDBC_URL");
		assertNotNull(url, "SESSION_TEST_JDBC_URL must point to a disposable PostgreSQL database named session_jdbc_test");
		dataSource = new DriverManagerDataSource(url, System.getenv("SESSION_TEST_DB_USER"), System.getenv("SESSION_TEST_DB_PASSWORD"));
		jdbc = new JdbcTemplate(dataSource);
		assertEquals("session_jdbc_test", jdbc.queryForObject("SELECT current_database()", String.class), "Refusing to modify a non-test database");
		first = JdbcSessionStore.create(dataSource, Duration.ofMinutes(30), true).getSessionRepository();
		jdbc.execute("TRUNCATE webui_session.spring_session CASCADE");
		second = restart();
	}

	private SessionRepository<? extends Session> restart()
	{
		return JdbcSessionStore.create(dataSource, Duration.ofMinutes(30), false).getSessionRepository();
	}

	private static <S extends Session> String create(final SessionRepository<S> repository)
	{
		final S session = repository.createSession();
		session.setAttribute("loggedIn", true);
		session.setAttribute("preferences", new ArrayList<>(Collections.singletonList("vi_VN")));
		repository.save(session);
		return session.getId();
	}

	private static <S extends Session> void update(final SessionRepository<S> repository, final String id, final Consumer<S> change)
	{
		final S session = repository.findById(id);
		assertNotNull(session);
		change.accept(session);
		repository.save(session);
	}

	@Test
	void anotherRepositoryAndRestartReadPersistedLogin()
	{
		final String id = create(first);
		assertEquals(Boolean.TRUE, second.findById(id).getAttribute("loggedIn"));
		assertEquals(Boolean.TRUE, restart().findById(id).getAttribute("loggedIn"));
	}

	@Test
	void actualSessionConfigReturnTypeWiresTheHttpSessionFilter() throws Exception
	{
		final Class<?> config = Class.forName("de.metas.ui.web.session.SessionConfig", false, getClass().getClassLoader());
		java.lang.reflect.Method factory = null;
		for (final java.lang.reflect.Method method : config.getDeclaredMethods())
		{
			if (method.getName().equals("sessionRepository"))
			{
				factory = method;
			}
		}
		assertNotNull(factory, "The actual SessionConfig must expose its repository factory");
		assertNotNull(factory.getAnnotation(Bean.class));
		try (AnnotationConfigApplicationContext context = new AnnotationConfigApplicationContext())
		{
			// Preserve the real factory's generic metadata while supplying the
			// disposable PostgreSQL repository instead of connecting to ERP.
			final RootBeanDefinition definition = new RootBeanDefinition(SessionRepository.class);
			definition.setTargetType(ResolvableType.forMethodReturnType(factory));
			definition.setInstanceSupplier(() -> first);
			context.registerBeanDefinition("sessionRepository", definition);
			context.register(SpringHttpSessionConfiguration.class);
			context.refresh();
			assertSame(first, context.getBean(SessionRepository.class));
			assertNotNull(context.getBean("springSessionRepositoryFilter"));
			final String id = create(first);
			assertEquals(Boolean.TRUE, restart().findById(id).getAttribute("loggedIn"));
		}
	}

	@Test
	void actualMetasfreshSessionBeanWithNestedIdentifiersSurvivesDatabaseRestart() throws Exception
	{
		final String id = saveActualSessionBean(first);
		final Object data = restart().findById(id).getAttribute("internalData");
		assertEquals("de.metas.ui.web.session.InternalUserSessionData", data.getClass().getName());
		assertEquals(Boolean.TRUE, field(data, "loggedIn"));
		final Object sessionId = field(data, "sessionId");
		assertEquals(id, sessionId.getClass().getMethod("getAsString").invoke(sessionId));
		final Object boilerPlate = field(data, "defaultBoilerPlateId");
		assertEquals(123, boilerPlate.getClass().getMethod("getRepoId").invoke(boilerPlate));
		final Object conditions = field(data, "defaultFlatrateConditionsId");
		assertEquals(456, conditions.getClass().getMethod("getRepoId").invoke(conditions));
		assertEquals("1000000", ((Properties)field(data, "ctx")).getProperty("#AD_User_ID"));
	}

	private static <S extends Session> String saveActualSessionBean(final SessionRepository<S> repository) throws Exception
	{
		final S session = repository.createSession();
		// Allocate the real class without its HTTP-request-dependent constructor.
		// This tests serialization of its actual field graph, not a replacement DTO.
		final Class<?> unsafeClass = Class.forName("sun.misc.Unsafe");
		final java.lang.reflect.Field access = unsafeClass.getDeclaredField("theUnsafe");
		access.setAccessible(true);
		final Object unsafe = access.get(null);
		final Class<?> beanClass = Class.forName("de.metas.ui.web.session.InternalUserSessionData");
		final Object data = unsafeClass.getMethod("allocateInstance", Class.class).invoke(unsafe, beanClass);
		setField(data, "initialized", true);
		setField(data, "loggedIn", true);
		setField(data, "locale", new Locale("vi", "VN"));
		final Properties context = new Properties();
		context.setProperty("#AD_User_ID", "1000000");
		context.setProperty("#AD_Role_ID", "1000000");
		setField(data, "ctx", context);
		setField(data, "sessionId", Class.forName("de.metas.ui.web.session.json.WebuiSessionId")
				.getMethod("ofString", String.class).invoke(null, session.getId()));
		setField(data, "defaultBoilerPlateId", Class.forName("de.metas.letter.BoilerPlateId")
				.getMethod("ofRepoId", int.class).invoke(null, 123));
		setField(data, "defaultFlatrateConditionsId", Class.forName("de.metas.contracts.ConditionsId")
				.getMethod("ofRepoId", int.class).invoke(null, 456));
		final Object preferences = Class.forName("de.metas.ui.web.session.UserPreference").newInstance();
		setField(preferences, "props", new Properties());
		setField(data, "userPreference", preferences);
		// Prove the fixture covers the incompatibility of the original serializer.
		assertThrows(org.springframework.core.serializer.support.SerializationFailedException.class,
				() -> new org.springframework.core.serializer.support.SerializingConverter().convert(data));
		session.setAttribute("internalData", data);
		repository.save(session);
		return session.getId();
	}

	private static Object field(final Object object, final String name) throws Exception
	{
		final java.lang.reflect.Field field = object.getClass().getDeclaredField(name);
		field.setAccessible(true);
		return field.get(object);
	}

	private static void setField(final Object object, final String name, final Object value) throws Exception
	{
		final java.lang.reflect.Field field = object.getClass().getDeclaredField(name);
		field.setAccessible(true);
		field.set(object, value);
	}

	@Test
	void mutableAttributeIsSavedWithoutSetAttribute()
	{
		final String id = create(first);
		update(second, id, session -> {
			final List<String> preferences = session.getAttribute("preferences");
			preferences.add("en_US");
		});
		final List<String> restored = restart().findById(id).getAttribute("preferences");
		assertEquals(2, restored.size());
		assertEquals("en_US", restored.get(1));
	}

	@Test
	void newAttributeReadBeforeSaveIsPersisted()
	{
		final String id = create(first);
		update(second, id, session -> {
			session.setAttribute("newPreference", new ArrayList<>(Collections.singletonList("vi_VN")));
			final List<String> value = session.getAttribute("newPreference");
			value.add("en_US");
		});
		final List<String> restored = restart().findById(id).getAttribute("newPreference");
		assertNotNull(restored);
		assertEquals(2, restored.size());
	}

	@Test
	void actualMetasfreshSessionBeanMutationSurvivesRestart() throws Exception
	{
		final String id = saveActualSessionBean(first);
		changeActualSessionBeanWithoutSetAttribute(second, id);
		final Object restored = restart().findById(id).getAttribute("internalData");
		assertEquals(Boolean.FALSE, field(restored, "loggedIn"));
	}

	private static <S extends Session> void changeActualSessionBeanWithoutSetAttribute(
			final SessionRepository<S> repository, final String id) throws Exception
	{
		final S session = repository.findById(id);
		final Object data = session.getAttribute("internalData");
		setField(data, "loggedIn", false);
		repository.save(session);
	}

	@Test
	void logoutInvalidatesOtherRepositoryAndCascadesAttributes()
	{
		final String id = create(first);
		first.deleteById(id);
		assertNull(second.findById(id));
		assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM webui_session.spring_session_attributes", Integer.class));
	}

	@Test
	void expiredLoginIsRejected()
	{
		final String id = create(first);
		update(first, id, session -> {
			session.setMaxInactiveInterval(Duration.ofSeconds(1));
			session.setLastAccessedTime(Instant.now().minusSeconds(60));
		});
		assertNull(second.findById(id));
	}

	@Test
	void scheduledCleanupRemovesExpiredRows()
	{
		final String id = create(first);
		update(first, id, session -> {
			session.setMaxInactiveInterval(Duration.ofSeconds(1));
			session.setLastAccessedTime(Instant.now().minusSeconds(60));
		});
		JdbcSessionStore.create(dataSource, null, false).run();
		assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM webui_session.spring_session", Integer.class));
	}

	@Test
	void schemaInitializationCanBeRepeated()
	{
		final String id = create(first);
		assertNotNull(JdbcSessionStore.create(dataSource, null, true).getSessionRepository().findById(id));
	}

	@Test
	void missingSchemaFailsBeforeTrafficIsAccepted()
	{
		jdbc.execute("DROP SCHEMA webui_session CASCADE");
		assertThrows(DataAccessException.class, () -> JdbcSessionStore.create(dataSource, null, false));
	}

	@Test
	void configuredTimeoutIsApplied()
	{
		assertEquals(Duration.ofMinutes(15), JdbcSessionStore.create(dataSource, Duration.ofMinutes(15), false)
				.getSessionRepository().createSession().getMaxInactiveInterval());
	}

	@Test
	void changingSessionIdInvalidatesThePreviousId()
	{
		final String id = create(first);
		final String[] newId = new String[1];
		update(first, id, session -> newId[0] = session.changeSessionId());
		assertNull(second.findById(id));
		assertEquals(Boolean.TRUE, restart().findById(newId[0]).getAttribute("loggedIn"));
	}

	@Test
	void concurrentRequestsCanIntroduceTheSameAttribute()
	{
		verifyConcurrentAttributeInsert(first, second, create(first));
	}

	private static <A extends Session, B extends Session> void verifyConcurrentAttributeInsert(
			final SessionRepository<A> a, final SessionRepository<B> b, final String id)
	{
		final A one = a.findById(id);
		final B two = b.findById(id);
		one.setAttribute("newPreference", "first");
		two.setAttribute("newPreference", "second");
		a.save(one);
		b.save(two);
		assertEquals("second", a.findById(id).getAttribute("newPreference"));
	}
}
