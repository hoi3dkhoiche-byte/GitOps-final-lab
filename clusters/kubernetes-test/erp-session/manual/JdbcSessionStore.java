package de.metas.ui.web.session.jdbc;

import java.io.IOException;
import java.io.InvalidObjectException;
import java.io.ObjectOutputStream;
import java.io.ObjectStreamException;
import java.io.OutputStream;
import java.io.Serializable;
import java.time.Duration;
import java.util.HashSet;
import java.util.Objects;
import java.util.logging.Level;
import java.util.logging.Logger;

import javax.sql.DataSource;

import org.springframework.core.io.ClassPathResource;
import org.springframework.core.convert.support.GenericConversionService;
import org.springframework.core.serializer.support.DeserializingConverter;
import org.springframework.core.serializer.support.SerializingConverter;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.session.SaveMode;
import org.springframework.session.Session;
import org.springframework.session.SessionRepository;
import org.springframework.session.jdbc.JdbcIndexedSessionRepository;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * PostgreSQL HTTP sessions using the application's existing connection pool.
 * No DataSource bean is registered, so business transaction configuration is unchanged.
 */
public final class JdbcSessionStore implements Runnable
{
	public static final String TABLE_NAME = "webui_session.spring_session";
	private static final Logger logger = Logger.getLogger(JdbcSessionStore.class.getName());
	private final JdbcIndexedSessionRepository repository;

	private JdbcSessionStore(final JdbcIndexedSessionRepository repository)
	{
		this.repository = repository;
	}

	public static JdbcSessionStore create(final DataSource dataSource, final Duration timeout, final boolean initializeSchema)
	{
		Objects.requireNonNull(dataSource, "Metasfresh database connection pool has not been initialized");
		final JdbcTemplate jdbc = new JdbcTemplate(dataSource);
		jdbc.setQueryTimeout(30);
		final TransactionTemplate transactions = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
		// Session commits must not depend on the success of an ERP business transaction.
		transactions.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);

		if (initializeSchema)
		{
			transactions.executeWithoutResult(status -> new ResourceDatabasePopulator(
					new ClassPathResource("schema-postgresql.sql", JdbcSessionStore.class)).execute(dataSource));
		}
		// Fail at startup if tables/permissions are missing, before accepting user traffic.
		jdbc.execute("SELECT PRIMARY_ID, SESSION_ID, CREATION_TIME, LAST_ACCESS_TIME, MAX_INACTIVE_INTERVAL, EXPIRY_TIME, PRINCIPAL_NAME FROM " + TABLE_NAME + " WHERE 1=0");
		jdbc.execute("SELECT SESSION_PRIMARY_ID, ATTRIBUTE_NAME, ATTRIBUTE_BYTES FROM " + TABLE_NAME + "_ATTRIBUTES WHERE 1=0");

		final JdbcIndexedSessionRepository repository = new JdbcIndexedSessionRepository(jdbc, transactions);
		repository.setTableName(TABLE_NAME);
		// The session bean is Serializable, but these three nested ID types are not.
		// Use stable serialized proxies and restore the original types on reading.
		final GenericConversionService converters = new GenericConversionService();
		converters.addConverter(Object.class, byte[].class, new SerializingConverter((value, output) -> serialize(value, output)));
		converters.addConverter(byte[].class, Object.class, new DeserializingConverter(JdbcSessionStore.class.getClassLoader()));
		repository.setConversionService(converters);
		if (timeout != null)
		{
			repository.setDefaultMaxInactiveInterval(Math.toIntExact(timeout.getSeconds()));
		}
		// Metasfresh mutates its session-scoped InternalUserSessionData in place.
		// Saving only setAttribute() calls would lose those mutations after a restart.
		repository.setSaveMode(SaveMode.ALWAYS);
		// Concurrent requests can both introduce the same attribute. PostgreSQL upsert
		// avoids a duplicate-key failure while retaining Spring Session's session lookup.
		repository.setCreateSessionAttributeQuery("INSERT INTO " + TABLE_NAME + "_ATTRIBUTES(SESSION_PRIMARY_ID, ATTRIBUTE_NAME, ATTRIBUTE_BYTES) "
				+ "SELECT PRIMARY_ID, ?, ? FROM " + TABLE_NAME + " WHERE SESSION_ID = ? "
				+ "ON CONFLICT (SESSION_PRIMARY_ID, ATTRIBUTE_NAME) DO UPDATE SET ATTRIBUTE_BYTES = EXCLUDED.ATTRIBUTE_BYTES");
		return new JdbcSessionStore(repository);
	}

	private static void serialize(final Object value, final OutputStream output) throws IOException
	{
		final ObjectOutputStream stream = new ObjectOutputStream(output)
		{
			{ enableReplaceObject(true); }

			@Override
			protected Object replaceObject(final Object object) throws IOException
			{
				if (object == null || !StoredId.supports(object.getClass().getName()))
				{
					return object;
				}
				final boolean text = object.getClass().getName().equals(StoredId.WEBUI_ID);
				try
				{
					final Object id = object.getClass().getMethod(text ? "getAsString" : "getRepoId").invoke(object);
					return new StoredId(object.getClass().getName(), String.valueOf(id));
				}
				catch (final ReflectiveOperationException ex)
				{
					throw new IOException("Could not serialize Metasfresh session ID type", ex);
				}
			}
		};
		stream.writeObject(value);
		stream.flush();
	}

	private static final class StoredId implements Serializable
	{
		private static final long serialVersionUID = 1L;
		private static final String WEBUI_ID = "de.metas.ui.web.session.json.WebuiSessionId";
		private final String type;
		private final String value;

		private StoredId(final String type, final String value)
		{
			this.type = type;
			this.value = value;
		}

		private static boolean supports(final String type)
		{
			return WEBUI_ID.equals(type) || "de.metas.letter.BoilerPlateId".equals(type)
					|| "de.metas.contracts.ConditionsId".equals(type);
		}

		private Object readResolve() throws ObjectStreamException
		{
			if (!supports(type))
			{
				throw new InvalidObjectException("Unsupported Metasfresh session ID type");
			}
			try
			{
				final Class<?> idClass = Class.forName(type, true, JdbcSessionStore.class.getClassLoader());
				return WEBUI_ID.equals(type)
						? idClass.getMethod("ofString", String.class).invoke(null, value)
						: idClass.getMethod("ofRepoId", int.class).invoke(null, Integer.parseInt(value));
			}
			catch (final ReflectiveOperationException | IllegalArgumentException ex)
			{
				final InvalidObjectException invalid = new InvalidObjectException("Could not restore Metasfresh session ID type");
				invalid.initCause(ex);
				throw invalid;
			}
		}
	}

	public SessionRepository<? extends Session> getSessionRepository()
	{
		return saveAllAttributes(repository);
	}

	private static <S extends Session> SessionRepository<S> saveAllAttributes(final SessionRepository<S> delegate)
	{
		// Spring Session JDBC 2.4.2 snapshots ALWAYS attributes before the result
		// extractor adds them. Mark them at save time to retain in-place mutations.
		return new SessionRepository<S>()
		{
			@Override
			public S createSession()
			{
				return delegate.createSession();
			}

			@Override
			public void save(final S session)
			{
				for (final String name : new HashSet<>(session.getAttributeNames()))
				{
					session.setAttribute(name, session.getAttribute(name));
				}
				delegate.save(session);
			}

			@Override
			public S findById(final String id)
			{
				return delegate.findById(id);
			}

			@Override
			public void deleteById(final String id)
			{
				delegate.deleteById(id);
			}
		};
	}

	@Override
	public void run()
	{
		try
		{
			repository.cleanUpExpiredSessions();
		}
		catch (final RuntimeException ex)
		{
			logger.log(Level.WARNING, "Failed cleaning expired JDBC sessions; the next scheduled run will retry", ex);
		}
	}
}
