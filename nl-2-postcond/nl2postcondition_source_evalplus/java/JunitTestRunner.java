import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Set;
import junit.framework.AssertionFailedError;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

public final class JunitTestRunner {
    private JunitTestRunner() {}

    public static void main(String[] rawArgs) {
        Arguments arguments;
        try {
            arguments = Arguments.parse(rawArgs);
        } catch (Throwable throwable) {
            System.out.println(RunResult.error(throwable).toJson());
            return;
        }

        try {
            Class<?> testClass = Class.forName(arguments.className);
            Request request = arguments.methodName.isEmpty()
                ? Request.aClass(testClass)
                : Request.method(testClass, arguments.methodName);

            Result result = new JUnitCore().run(request);
            List<String> failureMessages = new ArrayList<>();
            boolean assertionHit = false;
            for (Failure failure : result.getFailures()) {
                failureMessages.add(failure.toString());
                if (matchesInjectedAssertion(
                    failure.getException(),
                    arguments.sourceFileName,
                    arguments.assertLineNumbers
                )) {
                    assertionHit = true;
                }
            }

            int passedCount = Math.max(0, result.getRunCount() - result.getFailureCount() - result.getIgnoreCount());
            System.out.println(
                RunResult.success(
                    arguments.className,
                    arguments.methodName,
                    result.getRunCount(),
                    passedCount,
                    result.getFailureCount(),
                    result.getIgnoreCount(),
                    assertionHit,
                    failureMessages
                ).toJson()
            );
        } catch (Throwable throwable) {
            System.out.println(RunResult.error(throwable).toJson());
        }
    }

    private static boolean matchesInjectedAssertion(
        Throwable throwable,
        String sourceFileName,
        Set<Integer> assertLineNumbers
    ) {
        if (sourceFileName.isEmpty() || assertLineNumbers.isEmpty()) {
            return false;
        }

        Set<Throwable> seen = Collections.newSetFromMap(new IdentityHashMap<>());
        return matchesInjectedAssertionRecursive(throwable, sourceFileName, assertLineNumbers, seen);
    }

    private static boolean matchesInjectedAssertionRecursive(
        Throwable throwable,
        String sourceFileName,
        Set<Integer> assertLineNumbers,
        Set<Throwable> seen
    ) {
        if (throwable == null || seen.contains(throwable)) {
            return false;
        }
        seen.add(throwable);

        boolean assertionType = throwable instanceof AssertionError
            || throwable instanceof AssertionFailedError;
        if (assertionType) {
            for (StackTraceElement frame : throwable.getStackTrace()) {
                if (sourceFileName.equals(frame.getFileName())
                    && assertLineNumbers.contains(frame.getLineNumber())) {
                    return true;
                }
            }
        }

        for (Throwable suppressed : throwable.getSuppressed()) {
            if (matchesInjectedAssertionRecursive(
                suppressed,
                sourceFileName,
                assertLineNumbers,
                seen
            )) {
                return true;
            }
        }

        return matchesInjectedAssertionRecursive(
            throwable.getCause(),
            sourceFileName,
            assertLineNumbers,
            seen
        );
    }

    private static final class Arguments {
        private final String className;
        private final String methodName;
        private final String sourceFileName;
        private final Set<Integer> assertLineNumbers;

        private Arguments(
            String className,
            String methodName,
            String sourceFileName,
            Set<Integer> assertLineNumbers
        ) {
            this.className = className;
            this.methodName = methodName;
            this.sourceFileName = sourceFileName;
            this.assertLineNumbers = assertLineNumbers;
        }

        private static Arguments parse(String[] rawArgs) {
            if (rawArgs.length != 8) {
                throw new IllegalArgumentException("Expected 8 arguments, got " + rawArgs.length);
            }

            String className = "";
            String methodName = "";
            String sourceFileName = "";
            String assertLineValues = "";

            for (int index = 0; index < rawArgs.length; index += 2) {
                String flag = rawArgs[index];
                String value = rawArgs[index + 1];
                switch (flag) {
                    case "--class-name":
                        className = value;
                        break;
                    case "--method-name":
                        methodName = "-".equals(value) ? "" : value;
                        break;
                    case "--source-file":
                        sourceFileName = value;
                        break;
                    case "--assert-lines":
                        assertLineValues = value;
                        break;
                    default:
                        throw new IllegalArgumentException("Unknown argument: " + flag);
                }
            }

            if (className.isEmpty()) {
                throw new IllegalArgumentException("Missing test class name");
            }

            Set<Integer> assertLineNumbers = new HashSet<>();
            if (!assertLineValues.isEmpty()) {
                for (String value : assertLineValues.split(",")) {
                    if (!value.isBlank()) {
                        assertLineNumbers.add(Integer.parseInt(value.trim()));
                    }
                }
            }

            return new Arguments(className, methodName, sourceFileName, assertLineNumbers);
        }
    }

    private static final class RunResult {
        private final String status;
        private final String className;
        private final String methodName;
        private final int runCount;
        private final int passedCount;
        private final int failureCount;
        private final int ignoreCount;
        private final boolean assertionHit;
        private final List<String> failures;
        private final String message;

        private RunResult(
            String status,
            String className,
            String methodName,
            int runCount,
            int passedCount,
            int failureCount,
            int ignoreCount,
            boolean assertionHit,
            List<String> failures,
            String message
        ) {
            this.status = status;
            this.className = className;
            this.methodName = methodName;
            this.runCount = runCount;
            this.passedCount = passedCount;
            this.failureCount = failureCount;
            this.ignoreCount = ignoreCount;
            this.assertionHit = assertionHit;
            this.failures = failures;
            this.message = message;
        }

        private static RunResult success(
            String className,
            String methodName,
            int runCount,
            int passedCount,
            int failureCount,
            int ignoreCount,
            boolean assertionHit,
            List<String> failures
        ) {
            String status = failureCount == 0 ? "passed" : "failed";
            return new RunResult(
                status,
                className,
                methodName,
                runCount,
                passedCount,
                failureCount,
                ignoreCount,
                assertionHit,
                failures,
                ""
            );
        }

        private static RunResult error(Throwable throwable) {
            return new RunResult(
                "error",
                "",
                "",
                0,
                0,
                0,
                0,
                false,
                Collections.emptyList(),
                throwable.getClass().getSimpleName() + ": " + throwable.getMessage()
            );
        }

        private String toJson() {
            StringBuilder builder = new StringBuilder();
            builder.append("{");
            builder.append("\"status\":\"").append(escape(status)).append("\",");
            builder.append("\"class_name\":\"").append(escape(className)).append("\",");
            builder.append("\"method_name\":\"").append(escape(methodName)).append("\",");
            builder.append("\"run_count\":").append(runCount).append(",");
            builder.append("\"passed_count\":").append(passedCount).append(",");
            builder.append("\"failure_count\":").append(failureCount).append(",");
            builder.append("\"ignore_count\":").append(ignoreCount).append(",");
            builder.append("\"assertion_hit\":").append(assertionHit).append(",");
            builder.append("\"message\":\"").append(escape(message)).append("\",");
            builder.append("\"failures\":[");
            for (int index = 0; index < failures.size(); index++) {
                if (index > 0) {
                    builder.append(",");
                }
                builder.append("\"").append(escape(failures.get(index))).append("\"");
            }
            builder.append("]}");
            return builder.toString();
        }

        private static String escape(String value) {
            return value
                .replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r");
        }
    }
}
