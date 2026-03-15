import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import spoon.Launcher;
import spoon.reflect.CtModel;
import spoon.reflect.code.CtBlock;
import spoon.reflect.code.CtCodeSnippetStatement;
import spoon.reflect.code.CtExpression;
import spoon.reflect.code.CtLiteral;
import spoon.reflect.code.CtReturn;
import spoon.reflect.code.CtStatement;
import spoon.reflect.cu.SourcePosition;
import spoon.reflect.declaration.CtConstructor;
import spoon.reflect.declaration.CtElement;
import spoon.reflect.declaration.CtExecutable;
import spoon.reflect.declaration.CtMethod;
import spoon.reflect.declaration.CtParameter;
import spoon.reflect.factory.Factory;
import spoon.reflect.reference.CtTypeReference;
import spoon.reflect.visitor.filter.TypeFilter;

public final class Defects4JAssertionInjector {
    private static final String INTERNAL_RETURN_VALUE = "__nl2postcond_returnValue";
    private static final String ASSERTION_MARKER = "__NL2POSTCOND_ASSERTION_MARKER__";
    private static final Pattern ASSERT_KEYWORD = Pattern.compile("\\bassert\\b");
    private static final Pattern RETURN_VALUE_IDENTIFIER = Pattern.compile("\\breturnValue\\b");
    private static final Pattern LEADING_MODIFIER_PATTERN = Pattern.compile(
        "^(?:public|protected|private|static|final|abstract|synchronized|native|strictfp|default)\\b\\s*"
    );

    private Defects4JAssertionInjector() {}

    public static void main(String[] rawArgs) throws Exception {
        Arguments args = Arguments.parse(rawArgs);
        Result result;
        try {
            result = run(args);
        } catch (Throwable throwable) {
            result = Result.error(throwable);
        }
        writeResult(args.resultFile, result);
        if (!"ok".equals(result.status)) {
            System.exit(1);
        }
    }

    private static Result run(Arguments args) throws Exception {
        String assertionText = Files.readString(args.assertionFile, StandardCharsets.UTF_8).trim();
        Launcher launcher = new Launcher();
        launcher.addInputResource(args.sourceRoot.toString());
        launcher.getEnvironment().setCommentEnabled(true);
        launcher.getEnvironment().setNoClasspath(true);
        launcher.buildModel();

        CtExecutable<?> executable = findTarget(launcher.getModel(), args.relativeFile, args.methodSignature);
        if (executable.getBody() == null) {
            throw new IllegalStateException("Target executable has no body");
        }

        String executableKind;
        if (executable instanceof CtConstructor<?>) {
            executableKind = "constructor";
            String rewrittenAssertion = buildInstrumentedAssertion(
                replaceReturnValueIdentifier(assertionText, "this")
            );
            rewriteConstructor((CtConstructor<?>) executable, rewrittenAssertion, launcher.getFactory());
        } else if (executable instanceof CtMethod<?>) {
            CtMethod<?> method = (CtMethod<?>) executable;
            if (isVoidMethod(method)) {
                executableKind = "void_method";
                validateVoidAssertion(assertionText);
                String rewrittenAssertion = buildInstrumentedAssertion(assertionText);
                rewriteVoidMethod(method, rewrittenAssertion, launcher.getFactory());
            } else {
                executableKind = "method";
                String rewrittenAssertion = buildInstrumentedAssertion(
                    replaceReturnValueIdentifier(assertionText, INTERNAL_RETURN_VALUE)
                );
                rewriteNonVoidMethod(method, rewrittenAssertion, launcher.getFactory());
            }
        } else {
            throw new IllegalStateException(
                "Unsupported executable type: " + executable.getClass().getName()
            );
        }

        launcher.setSourceOutputDirectory(args.outputRoot.toFile());
        launcher.prettyprint();

        Path rewrittenFile = args.outputRoot.resolve(args.relativeFile);
        if (!Files.exists(rewrittenFile)) {
            throw new IllegalStateException("Spoon did not write rewritten file: " + rewrittenFile);
        }

        List<Integer> assertLines = collectAssertMarkerLines(rewrittenFile);
        if (assertLines.isEmpty()) {
            throw new IllegalStateException("Unable to locate injected assertion marker in rewritten file");
        }

        return Result.ok(executableKind, args.relativeFile, assertLines);
    }

    private static CtExecutable<?> findTarget(
        CtModel model,
        String relativeFile,
        String rawSignature
    ) {
        SignatureSelector selector = SignatureSelector.parse(rawSignature);
        List<ExecutableCandidate> candidates = collectExecutableCandidates(model, relativeFile);

        List<ExecutableCandidate> directMatches = findCanonicalMatches(
            candidates,
            selector.canonicalSignature
        );
        if (directMatches.size() == 1) {
            return directMatches.get(0).executable;
        }
        if (directMatches.size() > 1) {
            throw new IllegalStateException(
                buildAmbiguousResolutionMessage(rawSignature, relativeFile, "direct canonical match", directMatches)
            );
        }

        if (!selector.packageInsensitiveCanonicalSignature.equals(selector.canonicalSignature)) {
            List<ExecutableCandidate> packageInsensitiveMatches = findCanonicalMatches(
                candidates,
                selector.packageInsensitiveCanonicalSignature
            );
            if (packageInsensitiveMatches.size() == 1) {
                return packageInsensitiveMatches.get(0).executable;
            }
            if (packageInsensitiveMatches.size() > 1) {
                throw new IllegalStateException(
                    buildAmbiguousResolutionMessage(
                        rawSignature,
                        relativeFile,
                        "package-insensitive canonical match",
                        packageInsensitiveMatches
                    )
                );
            }
        }

        List<ExecutableCandidate> nameArityMatches = findNameArityMatches(candidates, selector);
        if (nameArityMatches.size() == 1) {
            return nameArityMatches.get(0).executable;
        }
        if (nameArityMatches.size() > 1) {
            throw new IllegalStateException(
                buildAmbiguousResolutionMessage(rawSignature, relativeFile, "name+arity fallback", nameArityMatches)
            );
        }

        List<ExecutableCandidate> nameMatches = findNameMatches(candidates, selector.executableName);
        if (nameMatches.size() == 1) {
            return nameMatches.get(0).executable;
        }
        if (nameMatches.size() > 1) {
            throw new IllegalStateException(
                buildAmbiguousResolutionMessage(rawSignature, relativeFile, "name-only fallback", nameMatches)
            );
        }

        throw new IllegalStateException(
            "Unable to resolve executable for " + rawSignature + " in " + relativeFile
                + "; available candidates: " + summarizeCandidates(candidates)
        );
    }

    private static List<ExecutableCandidate> collectExecutableCandidates(
        CtModel model,
        String relativeFile
    ) {
        List<ExecutableCandidate> candidates = new ArrayList<>();

        for (CtMethod<?> method : model.getElements(new TypeFilter<>(CtMethod.class))) {
            if (sameRelativeFile(method, relativeFile)) {
                candidates.add(ExecutableCandidate.from(method));
            }
        }

        for (CtConstructor<?> constructor : model.getElements(new TypeFilter<>(CtConstructor.class))) {
            if (sameRelativeFile(constructor, relativeFile)) {
                candidates.add(ExecutableCandidate.from(constructor));
            }
        }

        return candidates;
    }

    private static List<ExecutableCandidate> findCanonicalMatches(
        List<ExecutableCandidate> candidates,
        String expectedCanonicalSignature
    ) {
        List<ExecutableCandidate> matches = new ArrayList<>();
        for (ExecutableCandidate candidate : candidates) {
            if (candidate.canonicalSignature.equals(expectedCanonicalSignature)
                || candidate.packageInsensitiveCanonicalSignature.equals(expectedCanonicalSignature)) {
                matches.add(candidate);
            }
        }
        return matches;
    }

    private static List<ExecutableCandidate> findNameArityMatches(
        List<ExecutableCandidate> candidates,
        SignatureSelector selector
    ) {
        List<ExecutableCandidate> matches = new ArrayList<>();
        for (ExecutableCandidate candidate : candidates) {
            if (candidate.executableName.equals(selector.executableName)
                && candidate.arity == selector.arity) {
                matches.add(candidate);
            }
        }
        return matches;
    }

    private static List<ExecutableCandidate> findNameMatches(
        List<ExecutableCandidate> candidates,
        String executableName
    ) {
        List<ExecutableCandidate> matches = new ArrayList<>();
        for (ExecutableCandidate candidate : candidates) {
            if (candidate.executableName.equals(executableName)) {
                matches.add(candidate);
            }
        }
        return matches;
    }

    private static String buildAmbiguousResolutionMessage(
        String rawSignature,
        String relativeFile,
        String resolutionStage,
        List<ExecutableCandidate> matches
    ) {
        return "Ambiguous executable match for " + rawSignature + " in " + relativeFile
            + " via " + resolutionStage + ": " + summarizeCandidates(matches);
    }

    private static String summarizeCandidates(List<ExecutableCandidate> candidates) {
        if (candidates.isEmpty()) {
            return "(none)";
        }

        StringBuilder builder = new StringBuilder();
        int limit = Math.min(candidates.size(), 8);
        for (int index = 0; index < limit; index++) {
            if (index > 0) {
                builder.append(", ");
            }
            builder.append(candidates.get(index).canonicalSignature);
        }
        if (candidates.size() > limit) {
            builder.append(", ... total=").append(candidates.size());
        }
        return builder.toString();
    }

    private static boolean sameRelativeFile(CtElement element, String relativeFile) {
        SourcePosition position = element.getPosition();
        if (position == null || !position.isValidPosition() || position.getFile() == null) {
            return false;
        }
        String expected = normalizePath(relativeFile);
        String actual = normalizePath(position.getFile().getPath());
        return actual.endsWith("/" + expected) || actual.equals(expected);
    }

    private static String stripLeadingDecorations(String value) {
        String normalized = value.trim();

        while (true) {
            if (normalized.startsWith("@")) {
                String stripped = stripLeadingAnnotation(normalized);
                if (stripped.equals(normalized)) {
                    break;
                }
                normalized = stripped.trim();
                continue;
            }

            String strippedComment = stripLeadingComment(normalized);
            if (!strippedComment.equals(normalized)) {
                normalized = strippedComment.trim();
                continue;
            }
            break;
        }

        while (true) {
            Matcher modifierMatch = LEADING_MODIFIER_PATTERN.matcher(normalized);
            if (!modifierMatch.find()) {
                break;
            }
            normalized = normalized.substring(modifierMatch.end()).trim();
        }

        return normalized;
    }

    private static String stripLeadingAnnotation(String value) {
        int annotationEnd = skipAnnotation(value, 0);
        if (annotationEnd <= 0) {
            return value;
        }
        return value.substring(annotationEnd);
    }

    private static String stripLeadingComment(String value) {
        if (value.startsWith("//")) {
            int newlineIndex = value.indexOf('\n');
            return newlineIndex < 0 ? "" : value.substring(newlineIndex + 1);
        }
        if (value.startsWith("/*")) {
            int commentEnd = value.indexOf("*/");
            return commentEnd < 0 ? value : value.substring(commentEnd + 2);
        }
        return value;
    }

    private static String stripLeadingTypeParameters(String value) {
        String normalized = value.trim();
        if (!normalized.startsWith("<")) {
            return normalized;
        }

        int endIndex = findMatchingBracket(normalized, 0, '<', '>');
        if (endIndex < 0) {
            return normalized;
        }
        return normalized.substring(endIndex).trim();
    }

    private static int skipAnnotation(String value, int startIndex) {
        if (startIndex >= value.length() || value.charAt(startIndex) != '@') {
            return -1;
        }

        int index = startIndex + 1;
        if (index >= value.length() || !isAnnotationIdentifierStart(value.charAt(index))) {
            return -1;
        }

        index++;
        while (index < value.length() && isAnnotationIdentifierPart(value.charAt(index))) {
            index++;
        }

        while (index < value.length() && Character.isWhitespace(value.charAt(index))) {
            index++;
        }

        if (index < value.length() && value.charAt(index) == '(') {
            int endIndex = findMatchingBracket(value, index, '(', ')');
            if (endIndex < 0) {
                return -1;
            }
            index = endIndex;
        }

        return index;
    }

    private static int findMatchingBracket(
        String value,
        int startIndex,
        char openBracket,
        char closeBracket
    ) {
        int depth = 0;
        int index = startIndex;
        while (index < value.length()) {
            char current = value.charAt(index);
            if (current == '\'' || current == '"') {
                index = skipQuotedLiteral(value, index);
                continue;
            }
            if (current == openBracket) {
                depth++;
            } else if (current == closeBracket) {
                depth--;
                if (depth == 0) {
                    return index + 1;
                }
            }
            index++;
        }
        return -1;
    }

    private static int skipQuotedLiteral(String value, int quoteIndex) {
        char quote = value.charAt(quoteIndex);
        int index = quoteIndex + 1;
        while (index < value.length()) {
            char current = value.charAt(index);
            if (current == '\\') {
                index += 2;
                continue;
            }
            if (current == quote) {
                return index;
            }
            index++;
        }
        return value.length() - 1;
    }

    private static boolean isAnnotationIdentifierStart(char value) {
        return Character.isLetter(value) || value == '_';
    }

    private static boolean isAnnotationIdentifierPart(char value) {
        return Character.isLetterOrDigit(value) || value == '_' || value == '.' || value == '$';
    }

    private static String simpleExecutableName(String value) {
        String normalized = value.trim();
        int separatorIndex = Math.max(normalized.lastIndexOf('.'), normalized.lastIndexOf('$'));
        if (separatorIndex < 0) {
            return normalized;
        }
        return normalized.substring(separatorIndex + 1);
    }

    private static String buildInstrumentedAssertion(String assertionText) {
        Matcher matcher = ASSERT_KEYWORD.matcher(assertionText);
        if (!matcher.find()) {
            throw new IllegalStateException("Assertion text does not contain an assert statement");
        }
        return matcher.replaceFirst("/* " + ASSERTION_MARKER + " */ assert");
    }

    private static String replaceReturnValueIdentifier(String assertionText, String replacement) {
        return RETURN_VALUE_IDENTIFIER
            .matcher(assertionText)
            .replaceAll(Matcher.quoteReplacement(replacement));
    }

    private static void validateVoidAssertion(String assertionText) {
        if (RETURN_VALUE_IDENTIFIER.matcher(assertionText).find()) {
            throw new IllegalStateException(
                "Void-method assertions must not reference returnValue"
            );
        }
    }

    private static void rewriteVoidMethod(
        CtMethod<?> method,
        String assertionText,
        Factory factory
    ) {
        CtBlock<?> originalBody = method.getBody();
        CtBlock<?> newBody = factory.createBlock();
        newBody.addStatement(createSnippet(factory, assertionText));
        for (CtStatement statement : originalBody.getStatements()) {
            newBody.addStatement(statement.clone());
        }
        method.setBody((CtBlock) newBody);
    }

    private static void rewriteConstructor(
        CtConstructor<?> constructor,
        String assertionText,
        Factory factory
    ) {
        CtBlock<?> originalBody = constructor.getBody();
        CtBlock<?> newBody = factory.createBlock();
        for (CtStatement statement : originalBody.getStatements()) {
            newBody.addStatement(statement.clone());
        }
        newBody.addStatement(createSnippet(factory, assertionText));
        constructor.setBody((CtBlock) newBody);
    }

    private static void rewriteNonVoidMethod(
        CtMethod<?> method,
        String assertionText,
        Factory factory
    ) {
        List<CtReturn<?>> returns = new ArrayList<>();
        for (CtReturn<?> ctReturn : method.getBody().getElements(new TypeFilter<>(CtReturn.class))) {
            if (ctReturn.getParent(CtExecutable.class) == method) {
                returns.add(ctReturn);
            }
        }

        if (returns.isEmpty()) {
            throw new IllegalStateException("Non-void method contains no return statements");
        }

        String declaredReturnType = method.getType().clone().toString();
        String preferredReturnType = inferPreferredTemporaryReturnType(returns, declaredReturnType);

        for (CtReturn<?> originalReturn : returns) {
            CtExpression<?> returnedExpression = originalReturn.getReturnedExpression();
            if (returnedExpression == null) {
                throw new IllegalStateException("Encountered return without expression in non-void method");
            }

            CtBlock<?> replacement = factory.createBlock();
            String returnType = resolveTemporaryReturnType(
                returnedExpression,
                preferredReturnType,
                declaredReturnType
            );
            String returnExpression = returnedExpression.clone().toString();
            replacement.addStatement(
                createSnippet(
                    factory,
                    returnType + " " + INTERNAL_RETURN_VALUE + " = " + returnExpression + ";"
                )
            );
            replacement.addStatement(createSnippet(factory, assertionText));
            replacement.addStatement(createSnippet(factory, "return " + INTERNAL_RETURN_VALUE + ";"));

            originalReturn.replace(replacement);
        }
    }

    private static String inferPreferredTemporaryReturnType(
        List<CtReturn<?>> returns,
        String fallbackType
    ) {
        Set<String> nonNullReturnTypes = new LinkedHashSet<>();
        for (CtReturn<?> ctReturn : returns) {
            CtExpression<?> returnedExpression = ctReturn.getReturnedExpression();
            if (returnedExpression == null || isNullLiteral(returnedExpression)) {
                continue;
            }
            String expressionType = stringifyTypeReference(returnedExpression.getType());
            if (!expressionType.isEmpty()) {
                nonNullReturnTypes.add(expressionType);
                if (nonNullReturnTypes.size() > 1) {
                    return fallbackType;
                }
            }
        }
        if (nonNullReturnTypes.size() == 1) {
            return nonNullReturnTypes.iterator().next();
        }
        return fallbackType;
    }

    private static String resolveTemporaryReturnType(
        CtExpression<?> returnedExpression,
        String preferredReturnType,
        String fallbackType
    ) {
        if (!preferredReturnType.equals(fallbackType)) {
            return preferredReturnType;
        }
        if (!isNullLiteral(returnedExpression)) {
            String expressionType = stringifyTypeReference(returnedExpression.getType());
            if (!expressionType.isEmpty()) {
                return expressionType;
            }
        }
        return fallbackType;
    }

    private static boolean isNullLiteral(CtExpression<?> expression) {
        if (!(expression instanceof CtLiteral<?>)) {
            return false;
        }
        CtLiteral<?> literal = (CtLiteral<?>) expression;
        return literal.getValue() == null;
    }

    private static String stringifyTypeReference(CtTypeReference<?> typeReference) {
        if (typeReference == null) {
            return "";
        }
        return typeReference.clone().toString().trim();
    }

    private static CtCodeSnippetStatement createSnippet(Factory factory, String text) {
        String snippet = text.trim();
        if (snippet.endsWith(";")) {
            snippet = snippet.substring(0, snippet.length() - 1);
        }
        return factory.Code().createCodeSnippetStatement(snippet);
    }

    private static boolean isVoidMethod(CtMethod<?> method) {
        CtTypeReference<?> type = method.getType();
        if (type == null) {
            return false;
        }
        return "void".equals(type.getSimpleName()) || "void".equals(type.toString());
    }

    private static List<Integer> collectAssertMarkerLines(Path rewrittenFile) throws IOException {
        List<String> lines = Files.readAllLines(rewrittenFile, StandardCharsets.UTF_8);
        List<Integer> markerLines = new ArrayList<>();
        for (int index = 0; index < lines.size(); index++) {
            if (lines.get(index).contains(ASSERTION_MARKER)) {
                markerLines.add(index + 1);
            }
        }
        return markerLines;
    }

    private static String normalizePath(String value) {
        return value.replace('\\', '/');
    }

    private static String normalizeType(CtTypeReference<?> typeReference) {
        if (typeReference == null) {
            return "";
        }
        String raw = typeReference.toString();
        return normalizeType(raw);
    }

    private static String normalizeType(String raw) {
        String normalized = stripAllAnnotations(raw).trim().replace("...", "[]");
        normalized = normalized.replaceAll("\\bfinal\\b", "");
        normalized = normalized.replace("? extends ", "?");
        normalized = normalized.replace("? super ", "?");
        normalized = normalized.replaceAll("\\s+", "");
        return normalized;
    }

    private static String stripAllAnnotations(String raw) {
        StringBuilder builder = new StringBuilder();
        int index = 0;
        while (index < raw.length()) {
            if (raw.charAt(index) == '@') {
                int annotationEnd = skipAnnotation(raw, index);
                if (annotationEnd > index) {
                    index = annotationEnd;
                    continue;
                }
            }
            builder.append(raw.charAt(index));
            index++;
        }
        return builder.toString();
    }

    private static String stripPackages(String value) {
        String stripped = value;
        stripped = stripped.replaceAll("([A-Za-z_][A-Za-z0-9_$.]*\\.)+([A-Za-z_][A-Za-z0-9_$]*)", "$2");
        return stripped;
    }

    private static void writeResult(Path resultFile, Result result) throws IOException {
        Files.createDirectories(resultFile.getParent());
        Files.writeString(resultFile, result.toJson(), StandardCharsets.UTF_8);
    }

    private static final class Arguments {
        private final Path sourceRoot;
        private final String relativeFile;
        private final String methodSignature;
        private final Path assertionFile;
        private final Path outputRoot;
        private final Path resultFile;

        private Arguments(
            Path sourceRoot,
            String relativeFile,
            String methodSignature,
            Path assertionFile,
            Path outputRoot,
            Path resultFile
        ) {
            this.sourceRoot = sourceRoot;
            this.relativeFile = relativeFile;
            this.methodSignature = methodSignature;
            this.assertionFile = assertionFile;
            this.outputRoot = outputRoot;
            this.resultFile = resultFile;
        }

        private static Arguments parse(String[] rawArgs) {
            if (rawArgs.length != 12) {
                throw new IllegalArgumentException("Expected 12 arguments, got " + rawArgs.length);
            }

            Path sourceRoot = null;
            String relativeFile = null;
            String methodSignature = null;
            Path assertionFile = null;
            Path outputRoot = null;
            Path resultFile = null;

            for (int index = 0; index < rawArgs.length; index += 2) {
                String flag = rawArgs[index];
                String value = rawArgs[index + 1];
                switch (flag) {
                    case "--source-root":
                        sourceRoot = Path.of(value);
                        break;
                    case "--relative-file":
                        relativeFile = value;
                        break;
                    case "--method-signature":
                        methodSignature = value;
                        break;
                    case "--assertion-file":
                        assertionFile = Path.of(value);
                        break;
                    case "--output-root":
                        outputRoot = Path.of(value);
                        break;
                    case "--result-file":
                        resultFile = Path.of(value);
                        break;
                    default:
                        throw new IllegalArgumentException("Unknown argument: " + flag);
                }
            }

            if (sourceRoot == null
                || relativeFile == null
                || methodSignature == null
                || assertionFile == null
                || outputRoot == null
                || resultFile == null) {
                throw new IllegalArgumentException("Missing required arguments");
            }

            return new Arguments(
                sourceRoot,
                relativeFile,
                methodSignature,
                assertionFile,
                outputRoot,
                resultFile
            );
        }
    }

    private static final class SignatureSelector {
        private final String canonicalSignature;
        private final String packageInsensitiveCanonicalSignature;
        private final String executableName;
        private final int arity;

        private SignatureSelector(
            String canonicalSignature,
            String packageInsensitiveCanonicalSignature,
            String executableName,
            int arity
        ) {
            this.canonicalSignature = canonicalSignature;
            this.packageInsensitiveCanonicalSignature = packageInsensitiveCanonicalSignature;
            this.executableName = executableName;
            this.arity = arity;
        }

        private static SignatureSelector parse(String rawSignature) {
            String normalized = stripLeadingDecorations(rawSignature);
            normalized = stripLeadingTypeParameters(normalized);
            int closeParen = normalized.lastIndexOf(')');
            if (closeParen >= 0) {
                normalized = normalized.substring(0, closeParen + 1).trim();
            }

            int openParen = normalized.indexOf('(');
            if (openParen < 0 || closeParen < openParen) {
                throw new IllegalArgumentException("Invalid signature: " + rawSignature);
            }

            String prefix = normalized.substring(0, openParen).trim();
            String parameters = normalized.substring(openParen + 1, closeParen).trim();
            int separatorIndex = findLastTypeSeparator(prefix);
            String executableToken = separatorIndex < 0
                ? prefix
                : prefix.substring(separatorIndex + 1).trim();
            String executableName = simpleExecutableName(executableToken);
            String returnType = separatorIndex < 0
                ? ""
                : normalizeType(prefix.substring(0, separatorIndex).trim());

            List<ParameterDescriptor> parameterDescriptors = new ArrayList<>();
            if (!parameters.isEmpty()) {
                for (String parameter : splitTopLevel(parameters)) {
                    parameterDescriptors.add(ParameterDescriptor.parse(parameter));
                }
            }

            return new SignatureSelector(
                buildCanonicalSignature(returnType, executableName, parameterDescriptors, false),
                buildCanonicalSignature(returnType, executableName, parameterDescriptors, true),
                executableName,
                parameterDescriptors.size()
            );
        }

        private static String buildCanonicalSignature(
            String returnType,
            String executableName,
            List<ParameterDescriptor> parameterDescriptors,
            boolean packageInsensitive
        ) {
            StringBuilder builder = new StringBuilder();
            String canonicalReturnType = packageInsensitive ? stripPackages(returnType) : returnType;
            if (!canonicalReturnType.isEmpty()) {
                builder.append(canonicalReturnType);
            }
            builder.append(executableName).append("(");
            for (int index = 0; index < parameterDescriptors.size(); index++) {
                if (index > 0) {
                    builder.append(",");
                }
                builder.append(
                    packageInsensitive
                        ? parameterDescriptors.get(index).packageInsensitiveCanonicalDeclaration
                        : parameterDescriptors.get(index).canonicalDeclaration
                );
            }
            builder.append(")");
            return builder.toString();
        }

        private static List<String> splitTopLevel(String parameters) {
            if (parameters.isEmpty()) {
                return Collections.emptyList();
            }
            List<String> values = new ArrayList<>();
            StringBuilder current = new StringBuilder();
            int genericDepth = 0;
            int arrayDepth = 0;
            int parenthesisDepth = 0;
            for (int index = 0; index < parameters.length(); index++) {
                char currentChar = parameters.charAt(index);
                if (currentChar == '<') {
                    genericDepth++;
                } else if (currentChar == '>') {
                    genericDepth--;
                } else if (currentChar == '[') {
                    arrayDepth++;
                } else if (currentChar == ']') {
                    arrayDepth--;
                } else if (currentChar == '(') {
                    parenthesisDepth++;
                } else if (currentChar == ')') {
                    parenthesisDepth--;
                } else if (currentChar == ','
                    && genericDepth == 0
                    && arrayDepth == 0
                    && parenthesisDepth == 0) {
                    values.add(current.toString().trim());
                    current.setLength(0);
                    continue;
                }
                current.append(currentChar);
            }
            if (current.length() > 0) {
                values.add(current.toString().trim());
            }
            return values;
        }

        private static int findLastTypeSeparator(String parameter) {
            int genericDepth = 0;
            int arrayDepth = 0;
            int parenthesesDepth = 0;
            for (int index = parameter.length() - 1; index >= 0; index--) {
                char current = parameter.charAt(index);
                if (current == '>') {
                    genericDepth++;
                } else if (current == '<') {
                    genericDepth--;
                } else if (current == ']') {
                    arrayDepth++;
                } else if (current == '[') {
                    arrayDepth--;
                } else if (current == ')') {
                    parenthesesDepth++;
                } else if (current == '(') {
                    parenthesesDepth--;
                } else if (Character.isWhitespace(current)
                    && genericDepth == 0
                    && arrayDepth == 0
                    && parenthesesDepth == 0) {
                    return index;
                }
            }
            return -1;
        }
    }

    private static final class ParameterDescriptor {
        private final String canonicalDeclaration;
        private final String packageInsensitiveCanonicalDeclaration;

        private ParameterDescriptor(
            String canonicalDeclaration,
            String packageInsensitiveCanonicalDeclaration
        ) {
            this.canonicalDeclaration = canonicalDeclaration;
            this.packageInsensitiveCanonicalDeclaration = packageInsensitiveCanonicalDeclaration;
        }

        private static ParameterDescriptor parse(String rawParameter) {
            String normalized = stripLeadingDecorations(rawParameter);
            int separatorIndex = SignatureSelector.findLastTypeSeparator(normalized);
            String typePart = separatorIndex < 0 ? normalized : normalized.substring(0, separatorIndex).trim();
            String namePart = separatorIndex < 0 ? "" : normalized.substring(separatorIndex + 1).trim();

            String canonicalType = normalizeType(typePart);
            String canonicalName = namePart.replaceAll("\\s+", "");
            return new ParameterDescriptor(
                canonicalType + canonicalName,
                stripPackages(canonicalType) + canonicalName
            );
        }

        private static ParameterDescriptor fromParameter(CtParameter<?> parameter) {
            String typeText = parameter.getType() == null ? "" : parameter.getType().toString();
            String nameText = parameter.getSimpleName();
            return parse(typeText + " " + nameText);
        }
    }

    private static final class ExecutableCandidate {
        private final CtExecutable<?> executable;
        private final String canonicalSignature;
        private final String packageInsensitiveCanonicalSignature;
        private final String executableName;
        private final int arity;

        private ExecutableCandidate(
            CtExecutable<?> executable,
            String canonicalSignature,
            String packageInsensitiveCanonicalSignature,
            String executableName,
            int arity
        ) {
            this.executable = executable;
            this.canonicalSignature = canonicalSignature;
            this.packageInsensitiveCanonicalSignature = packageInsensitiveCanonicalSignature;
            this.executableName = executableName;
            this.arity = arity;
        }

        private static ExecutableCandidate from(CtExecutable<?> executable) {
            String executableName = "";
            String returnType = "";
            if (executable instanceof CtMethod<?>) {
                CtMethod<?> method = (CtMethod<?>) executable;
                executableName = method.getSimpleName();
                returnType = normalizeType(method.getType());
            } else if (executable instanceof CtConstructor<?>) {
                CtConstructor<?> constructor = (CtConstructor<?>) executable;
                if (constructor.getDeclaringType() != null) {
                    executableName = constructor.getDeclaringType().getSimpleName();
                }
            }

            List<ParameterDescriptor> parameterDescriptors = new ArrayList<>();
            for (CtParameter<?> parameter : executable.getParameters()) {
                parameterDescriptors.add(ParameterDescriptor.fromParameter(parameter));
            }

            return new ExecutableCandidate(
                executable,
                SignatureSelector.buildCanonicalSignature(returnType, executableName, parameterDescriptors, false),
                SignatureSelector.buildCanonicalSignature(returnType, executableName, parameterDescriptors, true),
                executableName,
                parameterDescriptors.size()
            );
        }
    }

    private static final class Result {
        private final String status;
        private final String executableKind;
        private final String relativeFile;
        private final List<Integer> assertLines;
        private final String message;

        private Result(
            String status,
            String executableKind,
            String relativeFile,
            List<Integer> assertLines,
            String message
        ) {
            this.status = status;
            this.executableKind = executableKind;
            this.relativeFile = relativeFile;
            this.assertLines = assertLines;
            this.message = message;
        }

        private static Result ok(
            String executableKind,
            String relativeFile,
            List<Integer> assertLines
        ) {
            return new Result("ok", executableKind, relativeFile, assertLines, "");
        }

        private static Result error(Throwable throwable) {
            return new Result(
                "error",
                "",
                "",
                Collections.emptyList(),
                throwable.getClass().getSimpleName() + ": " + throwable.getMessage()
            );
        }

        private String toJson() {
            StringBuilder builder = new StringBuilder();
            builder.append("{");
            builder.append("\"status\":\"").append(escape(status)).append("\",");
            builder.append("\"executable_kind\":\"").append(escape(executableKind)).append("\",");
            builder.append("\"relative_file\":\"").append(escape(relativeFile)).append("\",");
            builder.append("\"message\":\"").append(escape(message)).append("\",");
            builder.append("\"assert_lines\":[");
            for (int index = 0; index < assertLines.size(); index++) {
                if (index > 0) {
                    builder.append(",");
                }
                builder.append(assertLines.get(index));
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
