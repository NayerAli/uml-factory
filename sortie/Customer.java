import java.util.ArrayList;
import java.util.List;

/**
 * Cette classe contient les informations relatives à un client, telles que le nom
 * et le compte bancaire.
 */
public class Customer {

    private String name;

    /**
     * Agrégation bidirectionnelle avec BankAccount (role "owns").
     * Customer "1" o-- "1..*" BankAccount : "owns"
     */
    private List<BankAccount> accounts = new ArrayList<>();

    /**
     * Composition bidirectionnelle avec Wallet (role "holds").
     * Customer "1..*" *-- "1" Wallet : "holds"
     */
    private List<Wallet> wallets = new ArrayList<>();

    public Customer() {
    }

    public Customer(String name) {
        this.name = name;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public List<BankAccount> getAccounts() {
        return accounts;
    }

    public void setAccounts(List<BankAccount> accounts) {
        this.accounts = accounts;
    }

    public List<Wallet> getWallets() {
        return wallets;
    }

    public void setWallets(List<Wallet> wallets) {
        this.wallets = wallets;
    }

    /**
     * Ajoute un compte bancaire au client et synchronise l'autre côté
     * de l'association (titulaire principal).
     */
    public void addAccount(BankAccount account) {
        if (account != null && !accounts.contains(account)) {
            accounts.add(account);
            account.setPrimaryHolder(this);
        }
    }

    /**
     * Retire un compte bancaire du client en rompant l'association inverse.
     */
    public void removeAccount(BankAccount account) {
        if (account != null && accounts.remove(account)) {
            if (account.getPrimaryHolder() == this) {
                account.setPrimaryHolder(null);
            }
        }
    }

    /**
     * Ajoute un porte-monnaie détenu par le client (composition).
     */
    public void addWallet(Wallet wallet) {
        if (wallet != null && !wallets.contains(wallet)) {
            wallets.add(wallet);
        }
    }

    /**
     * Retire un porte-monnaie détenu par le client (composition).
     */
    public void removeWallet(Wallet wallet) {
        wallets.remove(wallet);
    }

    @Override
    public String toString() {
        return "Customer{name='" + name + "'}";
    }
}
