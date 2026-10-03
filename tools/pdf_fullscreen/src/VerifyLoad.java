public class VerifyLoad {
    public static void main(String[] a) throws Exception {
        for (String n : a) {
            try { Class.forName(n, true, VerifyLoad.class.getClassLoader()); System.out.println("OK   " + n); }
            catch (VerifyError e) { System.out.println("VERIFY-FAIL " + n + " : " + e.getMessage().split("\n")[0]); }
            catch (Throwable e) { System.out.println("verified(init err " + e.getClass().getSimpleName() + ") " + n); }
        }
    }
}
